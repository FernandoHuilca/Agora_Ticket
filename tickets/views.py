import json
import stripe
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.core.paginator import Paginator

from events.models import Event
from users.models import User
from users.permissions import role_required

from .forms import attendee_formset_factory
from .models import EventScanner, Reservation, Ticket, TicketValidation
from .services.reservations import (
    AgeRestricted,
    EventNotAvailable,
    PerUserLimitExceeded,
    SoldOut,
    create_reservation,
    release_reservation,
)
from .services.qr_signing import render_qr_png, sign_ticket
from .services.stripe_checkout import CheckoutError, create_checkout_session
from .services.stripe_webhook import process_stripe_event
from .services.validation import validate_ticket


BUYER_ROLES = (
    User.Role.CLIENT,
    User.Role.ORGANIZER,
    User.Role.SCANNER,
    User.Role.ADMIN,
)

RESERVATION_MESSAGES = {
    Reservation.Status.PENDING: (
        'Procesando pago...',
        'Estamos esperando la confirmación del pago. Esta página es informativa.',
    ),
    Reservation.Status.PAID: (
        'Compra confirmada',
        'Tu reserva fue confirmada. Tus tickets ya están disponibles.',
    ),
    Reservation.Status.EXPIRED: (
        'Reserva expirada',
        'La reserva ya no está disponible.',
    ),
    Reservation.Status.CANCELLED: (
        'Compra cancelada',
        'La reserva fue cancelada.',
    ),
}


def _redirect_see_other(url):
    response = HttpResponseRedirect(url)
    response.status_code = 303
    return response


def _purchase_limit(user, event):
    available = max(0, event.available_tickets)
    configured_limit = max(0, settings.TICKETS_MAX_PER_PURCHASE)
    limits = [available, configured_limit]
    reason = 'Agotado' if available == 0 else None

    if event.is_free:
        purchased = Ticket.objects.filter(
            reservation__user=user,
            event=event,
            status__in=[Ticket.Status.PENDING, Ticket.Status.ISSUED],
        ).count()
        remaining_for_user = max(0, event.max_tickets_per_user - purchased)
        limits.append(remaining_for_user)
        if remaining_for_user == 0 and reason is None:
            reason = 'Alcanzaste el límite por persona'

    max_num = min(limits)
    return max_num, reason


def _pay_context(request, event, formset=None, error=None):
    max_num, limit_reason = _purchase_limit(request.user, event)
    if formset is None and max_num > 0:
        formset = attendee_formset_factory(max_num)(initial=[{}])
    return {
        'event': event,
        'formset': formset,
        'max_num': max_num,
        'limit_reason': limit_reason,
        'error': error,
    }


@role_required(*BUYER_ROLES)
def pay(request, event_id):
    event = get_object_or_404(Event, pk=event_id)

    if request.method == 'GET':
        return render(request, 'tickets/pay.html', _pay_context(request, event))

    max_num, limit_reason = _purchase_limit(request.user, event)
    formset_class = attendee_formset_factory(max_num)
    formset = formset_class(request.POST)
    if max_num == 0:
        return render(
            request,
            'tickets/pay.html',
            _pay_context(request, event, formset=formset, error=limit_reason),
            status=400,
        )
    if not formset.is_valid():
        return render(
            request,
            'tickets/pay.html',
            _pay_context(request, event, formset=formset),
            status=400,
        )

    attendees = formset.cleaned_data
    try:
        reservation = create_reservation(request.user, event, attendees)
    except (
        AgeRestricted,
        EventNotAvailable,
        PerUserLimitExceeded,
        SoldOut,
        ValueError,
    ) as exc:
        messages_by_error = {
            SoldOut: 'No hay suficientes cupos disponibles.',
            PerUserLimitExceeded: 'Alcanzaste el límite de tickets por persona.',
            EventNotAvailable: 'Este evento ya no está disponible.',
            AgeRestricted: 'Este evento es solo para mayores de edad.',
        }
        error = messages_by_error.get(type(exc), str(exc))
        return render(
            request,
            'tickets/pay.html',
            _pay_context(request, event, formset=formset, error=error),
            status=400,
        )

    request.session['pending_reservation_id'] = str(reservation.id)
    if event.is_free:
        return _redirect_see_other(
            f'{reverse("tickets:ok")}?reservation_id={reservation.id}'
        )

    try:
        checkout_url = create_checkout_session(reservation)
    except CheckoutError as exc:
        messages.error(request, str(exc))
        return _redirect_see_other(reverse('tickets:cancel'))

    return _redirect_see_other(checkout_url)


@role_required(*BUYER_ROLES)
def cancel(request):
    reservation = None
    session_id = request.GET.get('session_id')
    reservation_id = (
        request.GET.get('reservation_id')
        or request.session.get('pending_reservation_id')
    )

    if session_id:
        reservation = Reservation.objects.filter(
            stripe_checkout_session_id=session_id,
            user=request.user,
        ).first()
    elif reservation_id:
        reservation = Reservation.objects.filter(
            pk=reservation_id,
            user=request.user,
        ).first()

    if reservation is not None:
        release_reservation(reservation)
        if request.session.get('pending_reservation_id') == str(reservation.id):
            request.session.pop('pending_reservation_id', None)

    return render(request, 'tickets/cancel.html')


@role_required(*BUYER_ROLES)
@require_GET
def ok(request):
    session_id = request.GET.get('session_id')
    reservation_id = request.GET.get('reservation_id')
    reservation = None
    if session_id:
        reservation = Reservation.objects.filter(
            stripe_checkout_session_id=session_id,
            user=request.user,
        ).select_related('event').first()
    elif reservation_id:
        reservation = Reservation.objects.filter(
            pk=reservation_id,
            user=request.user,
        ).select_related('event').first()

    status = reservation.status if reservation else Reservation.Status.PENDING
    heading, message = RESERVATION_MESSAGES.get(
        status,
        RESERVATION_MESSAGES[Reservation.Status.PENDING],
    )
    return render(request, 'tickets/ok.html', {
        'reservation': reservation,
        'session_id': session_id,
        'status_heading': heading,
        'status_message': message,
        'poll_reservation': bool(session_id and status == Reservation.Status.PENDING),
    })


@role_required(*BUYER_ROLES)
@require_GET
def reservation_status(request):
    session_id = request.GET.get('session_id')
    reservation = Reservation.objects.filter(
        stripe_checkout_session_id=session_id,
        user=request.user,
    ).first() if session_id else None
    if reservation is None:
        raise Http404
    return JsonResponse({'status': reservation.status})


@role_required(*BUYER_ROLES)
@require_GET
def my_tickets(request):
    tickets = Ticket.objects.filter(
        reservation__user=request.user,
    ).select_related('event', 'reservation').order_by('-issued_at', '-id')
    return render(request, 'tickets/tickets.html', {'tickets': tickets})


@role_required(*BUYER_ROLES)
@require_GET
def ticket_detail(request, pk):
    queryset = Ticket.objects.select_related(
        'event',
        'reservation__user',
    ).filter(
        Q(reservation__user=request.user)
        | Q(event__organizer=request.user)
    )
    if request.user.has_role(User.Role.ADMIN):
        queryset = Ticket.objects.select_related(
            'event',
            'reservation__user',
        )
    ticket = get_object_or_404(queryset, pk=pk)
    return render(request, 'tickets/tk.html', {'ticket': ticket})


@role_required(*BUYER_ROLES)
@require_GET
def ticket_qr(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related('reservation'),
        pk=pk,
        reservation__user=request.user,
        status=Ticket.Status.ISSUED,
    )
    token = sign_ticket(ticket.id, ticket.event_id, ticket.reservation.user_id)
    response = HttpResponse(render_qr_png(token), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response


def _validation_response(outcome):
    result = outcome.result
    status_codes = {
        TicketValidation.Result.VALID: 200,
        TicketValidation.Result.MALFORMED: 400,
        TicketValidation.Result.NOT_AUTHORIZED: 403,
        TicketValidation.Result.NOT_FOUND: 404,
        TicketValidation.Result.ALREADY_USED: 409,
        TicketValidation.Result.WRONG_EVENT: 409,
        TicketValidation.Result.CANCELLED: 409,
        TicketValidation.Result.TAMPERED: 422,
    }
    if result == TicketValidation.Result.VALID:
        body = {
            'result': result,
            'ticket': {
                'id': str(outcome.ticket.id),
                'event': outcome.ticket.event.name,
                'attendee_name': outcome.ticket.attendee_name,
            },
            'checked_in_at': outcome.checked_in_at.isoformat(),
        }
    elif result == TicketValidation.Result.ALREADY_USED:
        body = {
            'result': result,
            'checked_in_at': outcome.checked_in_at.isoformat()
            if outcome.checked_in_at else None,
            'checked_in_by': outcome.checked_in_by.email
            if outcome.checked_in_by else None,
        }
    else:
        body = {'result': result, 'message': outcome.message}
    return JsonResponse(body, status=status_codes[result])


def _allow_validation_request(user):
    key = f'tickets:validate:{user.pk}'
    count = cache.get(key)
    if count is None:
        cache.add(key, 1, timeout=60)
        return True
    if count >= 60:
        return False
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=60)
    return True


@role_required(User.Role.SCANNER, User.Role.ADMIN)
@require_POST
def validate_ticket_api(request):
    if not _allow_validation_request(request.user):
        return JsonResponse(
            {'result': 'RATE_LIMITED', 'message': 'Demasiadas solicitudes'},
            status=429,
        )

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    token = payload.get('token', '')
    if not isinstance(token, str):
        token = ''
    expected_event_id = None
    raw_expected_event_id = payload.get('expected_event_id')
    if raw_expected_event_id:
        try:
            expected_event_id = UUID(str(raw_expected_event_id))
        except (TypeError, ValueError):
            expected_event_id = None

    outcome = validate_ticket(
        token,
        request.user,
        expected_event_id,
        request.META.get('REMOTE_ADDR'),
    )
    return _validation_response(outcome)


@role_required(User.Role.SCANNER, User.Role.ADMIN)
@require_GET
def scan(request):
    if request.user.has_role(User.Role.ADMIN):
        events = Event.objects.all().order_by('start_date')
    else:
        events = Event.objects.filter(
            scanners__scanner=request.user,
        ).distinct().order_by('start_date')
    return render(request, 'tickets/scan.html', {'events': events})


@role_required(User.Role.SCANNER, User.Role.ORGANIZER, User.Role.ADMIN)
@require_GET
def validation_history(request):
    result = request.GET.get('result')
    if request.user.has_role(User.Role.ADMIN):
        validations = TicketValidation.objects.all()
    elif request.user.has_role(User.Role.ORGANIZER):
        validations = TicketValidation.objects.filter(
            event__organizer=request.user,
        )
    else:
        validations = TicketValidation.objects.filter(scanner=request.user)

    if result in TicketValidation.Result.values:
        validations = validations.filter(result=result)
    validations = validations.select_related(
        'ticket', 'event', 'scanner',
    ).order_by('-scanned_at')
    page = Paginator(validations, 20).get_page(request.GET.get('page'))
    return render(request, 'tickets/validation_history.html', {
        'page_obj': page,
        'result_filter': result or '',
        'result_choices': TicketValidation.Result.choices,
    })


@csrf_exempt
def stripe_webhook(request):
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])

    signature = request.META.get('HTTP_STRIPE_SIGNATURE')
    if not signature:
        return HttpResponse(status=400)

    try:
        event = stripe.Webhook.construct_event(
            request.body,
            signature,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)

    process_stripe_event(event)
    return HttpResponse(status=200)
