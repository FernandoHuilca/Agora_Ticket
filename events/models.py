import uuid
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from .validators import validate_event_image, sanitize_and_optimize_image


class Event(models.Model):
    MIN_DURATION_MINUTES = 30
    MAX_DURATION_HOURS = 24
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        PUBLISHED = 'PUBLISHED', 'Publicado'
        CANCELLED = 'CANCELLED', 'Cancelado'

    class Category(models.TextChoices):
        CONCERT = 'Concierto', 'Concierto'
        RECITAL = 'Recital', 'Recital'
        OPERA = 'Ópera', 'Ópera'
        SYMPHONIC = 'Sinfónico', 'Sinfónico'
        THEATER = 'Teatro Musical', 'Teatro Musical'
        OTHER = 'Otro', 'Otro'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='organized_events',
        verbose_name='Organizador responsable'
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moderated_events',
        verbose_name='Moderado por'
    )

    name = models.CharField(
        max_length=150,
        validators=[MinLengthValidator(5)],
        db_index=True,
        verbose_name='Nombre del evento'
    )
    description = models.TextField(
        validators=[MinLengthValidator(20)],
        max_length=2000,
        verbose_name='Descripción'
    )
    category = models.CharField(
        max_length=50,
        choices=Category.choices,
        default=Category.CONCERT,
        db_index=True,
        verbose_name='Categoría'
    )
    start_date = models.DateTimeField(
        db_index=True,
        verbose_name='Fecha y hora de inicio'
    )
    end_date = models.DateTimeField(
        verbose_name='Fecha y hora de finalización'
    )
    location = models.CharField(
        max_length=200,
        verbose_name='Ubicación / Sala'
    )

    capacity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Capacidad máxima (Aforo)'
    )
    available_tickets = models.PositiveIntegerField(
        verbose_name='Entradas disponibles'
    )

    is_free = models.BooleanField(
        default=False,
        verbose_name='¿Es gratuito?'
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Precio ($)'
    )
    is_adult_only = models.BooleanField(
        default=False,
        verbose_name='Restringido a mayores de edad (+18)'
    )
    max_tickets_per_user = models.PositiveIntegerField(
        default=4,
        validators=[MinValueValidator(1)],
        verbose_name='Máximo de tickets por persona (eventos gratuitos)'
    )

    image = models.ImageField(
        upload_to='events/%Y/%m/',
        null=True,
        blank=True,
        validators=[validate_event_image],
        verbose_name='Afiche del evento'
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
        verbose_name='Estado de publicación'
    )
    moderation_notes = models.TextField(
        null=True,
        blank=True,
        max_length=500,
        verbose_name='Observaciones de moderación'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Evento'
        verbose_name_plural = 'Eventos'
        ordering = ['start_date']
        indexes = [
            models.Index(fields=['status', 'start_date'], name='idx_event_status_start'),
            models.Index(fields=['category', 'status'], name='idx_event_category_status'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__gt=0),
                name='chk_event_capacity_positive'
            ),
            models.CheckConstraint(
                condition=Q(available_tickets__lte=models.F('capacity')),
                name='chk_available_lte_capacity'
            ),
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name='chk_event_price_non_negative'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        errors = {}

        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                errors['end_date'] = 'La fecha de finalización debe ser posterior a la fecha de inicio.'
            else:
                duration = self.end_date - self.start_date
                if duration < timedelta(minutes=self.MIN_DURATION_MINUTES):
                    errors['end_date'] = (
                        f'El evento debe tener una duración mínima de {self.MIN_DURATION_MINUTES} minutos.'
                    )
                elif duration > timedelta(hours=self.MAX_DURATION_HOURS):
                    errors['end_date'] = (
                        f'La duración de un evento individual no puede exceder las {self.MAX_DURATION_HOURS} horas.'
                    )

        if self.is_free and self.price and self.price > Decimal('0.00'):
            errors['price'] = 'Un evento gratuito debe tener precio $0.00.'

        if not self.is_free and (self.price is None or self.price <= Decimal('0.00')):
            errors['price'] = 'Un evento de pago debe tener un precio mayor a $0.00.'

        if self.capacity is not None and self.available_tickets is not None:
            if self.available_tickets > self.capacity:
                errors['available_tickets'] = 'Los cupos disponibles no pueden superar la capacidad máxima.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Si es creación nueva y no se especificó available_tickets, igualar a capacity
        if self._state.adding and self.available_tickets is None:
            self.available_tickets = self.capacity
        self.full_clean()

        # Si hay una imagen nueva en memoria aún no guardada, sanitizarla quitando EXIF
        if self.image and getattr(self.image, '_committed', True) is False:
            self.image = sanitize_and_optimize_image(self.image)

        super().save(*args, **kwargs)
