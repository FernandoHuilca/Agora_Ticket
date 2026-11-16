from django.core.management.base import BaseCommand
from django.utils import timezone

from tickets.models import Reservation
from tickets.services.reservations import release_reservation


class Command(BaseCommand):
    help = 'Libera reservas pendientes cuyo tiempo de espera ya expiró.'

    def handle(self, *args, **options):
        expired_reservations = Reservation.objects.filter(
            status=Reservation.Status.PENDING,
            expires_at__lte=timezone.now(),
        )
        released_count = 0

        for reservation in expired_reservations:
            if release_reservation(reservation):
                released_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Reservas liberadas: {released_count}'
            )
        )
