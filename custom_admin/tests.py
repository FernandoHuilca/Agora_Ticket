from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from users.models import User


class CustomAdminDashboardIntegrationTests(TestCase):
    def setUp(self):
        self.business_admin = User.objects.create_user(
            email="admin_negocio@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ADMIN,
            is_staff=False,
            is_superuser=False,
        )
        self.super_admin = User.objects.create_superuser(
            email="super@casadelamusica.ec",
            password="PasswordSegura123!",
        )
        self.organizer = User.objects.create_user(
            email="org@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ORGANIZER,
        )
        self.client_user = User.objects.create_user(
            email="cliente@epn.edu.ec",
            password="PasswordSegura123!",
            role=User.Role.CLIENT,
        )
        self.now = timezone.now()
        self.active_event = Event.objects.create(
            organizer=self.organizer,
            name="Concierto Sinfónico en Dashboard",
            description="Evento publicado vigente que debe mostrarse en el dashboard.",
            category=Event.Category.SYMPHONIC,
            start_date=self.now + timedelta(days=5),
            end_date=self.now + timedelta(days=5, hours=2),
            location="Sala Principal",
            capacity=100,
            available_tickets=85,
            is_free=False,
            price=Decimal("15.00"),
            status=Event.Status.PUBLISHED,
        )

    def test_unauthenticated_and_non_admin_redirect_to_custom_login(self):
        """Usuarios sin permisos son redirigidos al login personalizado (users:login)."""
        dashboard_url = reverse("custom_admin:dashboard_home")
        expected_login_url = f"{reverse('users:login')}?next={dashboard_url}"

        res_anon = self.client.get(dashboard_url)
        self.assertRedirects(res_anon, expected_login_url)

        self.client.force_login(self.client_user)
        res_client = self.client.get(dashboard_url)
        self.assertRedirects(res_client, expected_login_url, fetch_redirect_response=False)

    def test_business_admin_can_access_dashboard_and_hides_django_admin_link(self):
        """
        El admin de negocio (sin is_superuser) accede al dashboard, se contabiliza en total_admins,
        ve los eventos vigentes con opciones de detalle/cancelar y NO ve el enlace a /admin/.
        """
        self.client.force_login(self.business_admin)
        response = self.client.get(reverse("custom_admin:dashboard_home"))
        self.assertEqual(response.status_code, 200)

        # Métricas incluyen tanto al admin de negocio como al superusuario (2 en total)
        self.assertEqual(response.context["total_admins"], 2)
        self.assertEqual(response.context["total_eventos"], 1)
        self.assertEqual(response.context["tickets_vendidos"], 15)

        # Conecta con eventos publicados vigentes y sus acciones
        self.assertContains(response, self.active_event.name)
        self.assertContains(response, reverse("events:detail", kwargs={"pk": self.active_event.pk}))
        self.assertContains(response, reverse("events:cancel", kwargs={"pk": self.active_event.pk}))
        self.assertContains(response, reverse("events:moderation_list"))

        # Oculta el enlace al Panel Técnico Django para un admin de negocio no superusuario
        self.assertNotContains(response, 'href="/admin/"')

    def test_superuser_sees_django_technical_admin_link(self):
        """El superusuario sí visualiza el enlace al Panel Técnico Django (/admin/)."""
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("custom_admin:dashboard_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/admin/"')
