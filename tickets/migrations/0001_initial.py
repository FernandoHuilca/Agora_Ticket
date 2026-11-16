import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('events', '0003_alter_event_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='Reservation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('PENDING', 'Pendiente'), ('PAID', 'Pagada'), ('EXPIRED', 'Expirada'), ('CANCELLED', 'Cancelada')], db_index=True, default='PENDING', max_length=10)),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))])),
                ('currency', models.CharField(default='usd', max_length=3)),
                ('expires_at', models.DateTimeField()),
                ('stripe_checkout_session_id', models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reservations', to='events.event')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ticket_reservations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_payment_intent_id', models.CharField(max_length=255, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))])),
                ('status', models.CharField(choices=[('PENDING', 'Pendiente'), ('PAID', 'Pagado'), ('FAILED', 'Fallido'), ('REFUNDED', 'Reembolsado')], db_index=True, default='PENDING', max_length=10)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('reservation', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='payment', to='tickets.reservation')),
            ],
        ),
        migrations.CreateModel(
            name='StripeEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.CharField(max_length=255, unique=True)),
                ('type', models.CharField(max_length=100)),
                ('processed_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='Ticket',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('attendee_name', models.CharField(max_length=150)),
                ('attendee_email', models.EmailField(blank=True, max_length=254)),
                ('status', models.CharField(choices=[('PENDING', 'Pendiente'), ('ISSUED', 'Emitido'), ('CANCELLED', 'Cancelado'), ('REFUNDED', 'Reembolsado')], db_index=True, default='PENDING', max_length=10)),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))])),
                ('qr_payload_hash', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('issued_at', models.DateTimeField(blank=True, null=True)),
                ('is_checked_in', models.BooleanField(default=False)),
                ('checked_in_at', models.DateTimeField(blank=True, null=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tickets', to='events.event')),
                ('reservation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tickets', to='tickets.reservation')),
                ('checked_in_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='checked_in_tickets', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['event', 'status'], name='idx_ticket_event_status')],
                'constraints': [
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
                ],
            },
        ),
        migrations.CreateModel(
            name='EventScanner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='scanners', to='events.event')),
                ('scanner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='scanner_assignments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('event', 'scanner'), name='uq_event_scanner'),
                ],
            },
        ),
        migrations.CreateModel(
            name='TicketValidation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('result', models.CharField(choices=[('VALID', 'Válido'), ('TAMPERED', 'Alterado'), ('MALFORMED', 'Malformado'), ('NOT_FOUND', 'No encontrado'), ('WRONG_EVENT', 'Evento incorrecto'), ('NOT_AUTHORIZED', 'No autorizado'), ('ALREADY_USED', 'Ya utilizado'), ('CANCELLED', 'Cancelado')], max_length=20)),
                ('scanned_at', models.DateTimeField(auto_now_add=True)),
                ('token_fingerprint', models.CharField(max_length=64)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ticket_validations', to='events.event')),
                ('scanner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ticket_validations', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='validations', to='tickets.ticket')),
            ],
            options={
                'indexes': [models.Index(fields=['scanned_at'], name='idx_ticket_validation_scanned')],
            },
        ),
    ]
