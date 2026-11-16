from django.contrib import admin

from .models import (
    EventScanner,
    Payment,
    Reservation,
    StripeEvent,
    Ticket,
    TicketValidation,
)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'event', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'currency')
    search_fields = ('id', 'user__email', 'event__name')
    readonly_fields = ('id', 'created_at', 'stripe_checkout_session_id')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('reservation', 'stripe_payment_intent_id', 'amount', 'status', 'paid_at')
    list_filter = ('status',)
    search_fields = (
        'reservation__id',
        'reservation__user__email',
        'reservation__event__name',
        'stripe_payment_intent_id',
    )
    readonly_fields = ('stripe_payment_intent_id', 'paid_at')


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'type', 'processed_at')
    list_filter = ('type',)
    search_fields = ('event_id', 'type')
    readonly_fields = ('event_id', 'type', 'processed_at')


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'event',
        'reservation',
        'status',
        'is_checked_in',
        'issued_at',
    )
    list_filter = ('status', 'is_checked_in')
    search_fields = ('id', 'reservation__user__email', 'event__name')
    readonly_fields = (
        'id',
        'qr_payload_hash',
        'issued_at',
        'is_checked_in',
        'checked_in_at',
        'checked_in_by',
    )


@admin.register(EventScanner)
class EventScannerAdmin(admin.ModelAdmin):
    list_display = ('event', 'scanner')
    list_filter = ('event', 'scanner')
    search_fields = ('event__name', 'scanner__email')


@admin.register(TicketValidation)
class TicketValidationAdmin(admin.ModelAdmin):
    list_display = ('result', 'ticket', 'event', 'scanner', 'scanned_at', 'ip')
    list_filter = ('result',)
    search_fields = (
        'ticket__id',
        'event__name',
        'scanner__email',
        'token_fingerprint',
    )
    readonly_fields = (
        'ticket',
        'event',
        'scanner',
        'result',
        'scanned_at',
        'token_fingerprint',
        'ip',
    )
