from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from users.models import User

from ..models import EventScanner, Ticket, TicketValidation
from .qr_signing import MalformedToken, fingerprint, parse_token, verify_signature


@dataclass(frozen=True)
class ValidationOutcome:
    result: str
    ticket: Optional[Ticket] = None
    checked_in_at: Optional[datetime] = None
    checked_in_by: Optional[User] = None
    message: str = ''


def _audit(result, scanner, token, *, ticket=None, event=None, ip=None):
    TicketValidation.objects.create(
        ticket=ticket,
        event=event,
        scanner=scanner,
        result=result,
        token_fingerprint=fingerprint(token),
        ip=ip,
    )


def _outcome(result, scanner, token, ip, *, ticket=None, event=None, message=''):
    _audit(
        result,
        scanner,
        token,
        ticket=ticket,
        event=event,
        ip=ip,
    )
    return ValidationOutcome(result=result, ticket=ticket, message=message)


def validate_ticket(
    token: str,
    scanner: User,
    expected_event_id: UUID | None,
    ip: str | None,
) -> ValidationOutcome:
    try:
        parsed = parse_token(token)
    except MalformedToken:
        return _outcome(
            TicketValidation.Result.MALFORMED,
            scanner,
            token,
            ip,
            message='Código QR malformado',
        )

    if not verify_signature(parsed):
        return _outcome(
            TicketValidation.Result.TAMPERED,
            scanner,
            token,
            ip,
            message='Código alterado o inválido',
        )

    ticket = (
        Ticket.objects.select_related('event', 'reservation__user', 'checked_in_by')
        .filter(pk=parsed.ticket_id)
        .first()
    )
    if ticket is None:
        return _outcome(
            TicketValidation.Result.NOT_FOUND,
            scanner,
            token,
            ip,
            message='Ticket inexistente',
        )

    if ticket.event_id != parsed.event_id or ticket.reservation.user_id != parsed.user_id:
        return _outcome(
            TicketValidation.Result.TAMPERED,
            scanner,
            token,
            ip,
            ticket=ticket,
            event=ticket.event,
            message='Código alterado o inválido',
        )

    is_admin = scanner.has_role(User.Role.ADMIN)
    is_assigned = EventScanner.objects.filter(
        event_id=ticket.event_id,
        scanner=scanner,
    ).exists() and scanner.has_role(User.Role.SCANNER)
    if not is_admin and not is_assigned:
        return _outcome(
            TicketValidation.Result.NOT_AUTHORIZED,
            scanner,
            token,
            ip,
            ticket=ticket,
            event=ticket.event,
            message='No estás autorizado para este evento',
        )

    if expected_event_id is not None and str(expected_event_id) != str(ticket.event_id):
        return _outcome(
            TicketValidation.Result.WRONG_EVENT,
            scanner,
            token,
            ip,
            ticket=ticket,
            event=ticket.event,
            message='El ticket pertenece a otro evento',
        )

    if ticket.status != Ticket.Status.ISSUED:
        return _outcome(
            TicketValidation.Result.CANCELLED,
            scanner,
            token,
            ip,
            ticket=ticket,
            event=ticket.event,
            message='El ticket no está disponible',
        )

    now = timezone.now()
    with transaction.atomic():
        updated = Ticket.objects.filter(
            pk=ticket.pk,
            status=Ticket.Status.ISSUED,
            is_checked_in=False,
        ).update(
            is_checked_in=True,
            checked_in_at=now,
            checked_in_by=scanner,
        )
        if updated:
            ticket.checked_in_at = now
            ticket.checked_in_by = scanner
            _audit(
                TicketValidation.Result.VALID,
                scanner,
                token,
                ticket=ticket,
                event=ticket.event,
                ip=ip,
            )
            return ValidationOutcome(
                result=TicketValidation.Result.VALID,
                ticket=ticket,
                checked_in_at=now,
                checked_in_by=scanner,
            )

        used_ticket = Ticket.objects.select_related('checked_in_by').get(pk=ticket.pk)
        _audit(
            TicketValidation.Result.ALREADY_USED,
            scanner,
            token,
            ticket=used_ticket,
            event=ticket.event,
            ip=ip,
        )
        return ValidationOutcome(
            result=TicketValidation.Result.ALREADY_USED,
            ticket=used_ticket,
            checked_in_at=used_ticket.checked_in_at,
            checked_in_by=used_ticket.checked_in_by,
            message='El ticket ya fue utilizado',
        )
