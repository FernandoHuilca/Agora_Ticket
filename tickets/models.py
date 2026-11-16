import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        PAID = 'PAID', 'Pagada'
        EXPIRED = 'EXPIRED', 'Expirada'
        CANCELLED = 'CANCELLED', 'Cancelada'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ticket_reservations',
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        related_name='reservations',
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    currency = models.CharField(max_length=3, default='usd')
    expires_at = models.DateTimeField()
    stripe_checkout_session_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.id} - {self.get_status_display()}'


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        PAID = 'PAID', 'Pagado'
        FAILED = 'FAILED', 'Fallido'
        REFUNDED = 'REFUNDED', 'Reembolsado'

    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.PROTECT,
        related_name='payment',
    )
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.reservation_id} - {self.get_status_display()}'


class StripeEvent(models.Model):
    event_id = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.type} ({self.event_id})'


class Ticket(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        ISSUED = 'ISSUED', 'Emitido'
        CANCELLED = 'CANCELLED', 'Cancelado'
        REFUNDED = 'REFUNDED', 'Reembolsado'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name='tickets',
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        related_name='tickets',
    )
    attendee_name = models.CharField(max_length=150)
    attendee_email = models.EmailField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    qr_payload_hash = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    is_checked_in = models.BooleanField(default=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='checked_in_tickets',
    )

    class Meta:
        indexes = [
            models.Index(fields=['event', 'status'], name='idx_ticket_event_status'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_checked_in=False)
                    | (
                        models.Q(status='ISSUED')
                        & models.Q(checked_in_at__isnull=False)
                    )
                ),
                name='chk_ticket_check_in_consistent',
            ),
        ]

    def __str__(self):
        return f'{self.id} - {self.get_status_display()}'


class EventScanner(models.Model):
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        related_name='scanners',
    )
    scanner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='scanner_assignments',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'scanner'],
                name='uq_event_scanner',
            ),
        ]

    def __str__(self):
        return f'{self.event} - {self.scanner}'


class TicketValidation(models.Model):
    class Result(models.TextChoices):
        VALID = 'VALID', 'Válido'
        TAMPERED = 'TAMPERED', 'Alterado'
        MALFORMED = 'MALFORMED', 'Malformado'
        NOT_FOUND = 'NOT_FOUND', 'No encontrado'
        WRONG_EVENT = 'WRONG_EVENT', 'Evento incorrecto'
        NOT_AUTHORIZED = 'NOT_AUTHORIZED', 'No autorizado'
        ALREADY_USED = 'ALREADY_USED', 'Ya utilizado'
        CANCELLED = 'CANCELLED', 'Cancelado'

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='validations',
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ticket_validations',
    )
    scanner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ticket_validations',
    )
    result = models.CharField(max_length=20, choices=Result.choices)
    scanned_at = models.DateTimeField(auto_now_add=True)
    token_fingerprint = models.CharField(max_length=64)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['scanned_at'], name='idx_ticket_validation_scanned'),
        ]

    def __str__(self):
        return f'{self.result} - {self.scanned_at}'
