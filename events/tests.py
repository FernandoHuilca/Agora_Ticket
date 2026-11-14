from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from PIL import Image

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from .models import Event

User = get_user_model()


def create_valid_image():
    buf = BytesIO()
    img = Image.new("RGB", (200, 200), color=(120, 40, 60))
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile("afiche.jpg", buf.read(), content_type="image/jpeg")


class EventModelTDDTests(TestCase):
    def setUp(self):
        # Crea un usuario compatible tanto si username es requerido como si usan solo email
        user_kwargs = {"password": "PasswordSegura123!"}
        if hasattr(User, "USERNAME_FIELD") and User.USERNAME_FIELD == "email":
            user_kwargs["email"] = "organizador@casadelamusica.ec"
        else:
            user_kwargs["username"] = "org_test"
            user_kwargs["email"] = "organizador@casadelamusica.ec"

        self.organizer = User.objects.create_user(**user_kwargs)
        self.start = timezone.now() + timedelta(days=7)
        self.end = self.start + timedelta(hours=2)

    def test_event_shorter_than_minimum_duration_raises_error(self):
        """Regla de negocio: un evento no puede durar menos de 30 minutos (ej. 1 minuto)."""
        event = Event(
            organizer=self.organizer,
            name="Micro Recital Express",
            description="Prueba de evento con duración demasiado corta de un minuto.",
            category=Event.Category.RECITAL,
            start_date=self.start,
            end_date=self.start + timedelta(minutes=1),
            location="Sala de Recitales",
            capacity=50,
            is_free=True,
            price=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("end_date", ctx.exception.message_dict)

    def test_create_valid_event_initializes_available_tickets(self):
        """Al crear un evento válido, available_tickets se inicializa igual a capacity y nace PUBLISHED."""
        event = Event.objects.create(
            organizer=self.organizer,
            name="Concierto Sinfónico de Apertura",
            description="Presentación de la Orquesta Sinfónica con obras clásicas.",
            category=Event.Category.SYMPHONIC,
            start_date=self.start,
            end_date=self.end,
            location="Sala Principal",
            capacity=150,
            is_free=False,
            price=Decimal("20.00"),
            image=create_valid_image(),
        )
        self.assertEqual(event.available_tickets, 150)
        self.assertEqual(event.status, Event.Status.PUBLISHED)

    def test_free_event_with_positive_price_raises_error(self):
        """Un evento gratuito no puede tener precio mayor a cero."""
        event = Event(
            organizer=self.organizer,
            name="Recital de Piano Abierto",
            description="Recital cultural gratuito para toda la comunidad.",
            category=Event.Category.RECITAL,
            start_date=self.start,
            end_date=self.end,
            location="Sala de Recitales",
            capacity=80,
            is_free=True,
            price=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("price", ctx.exception.message_dict)

    def test_end_date_before_start_date_raises_error(self):
        """La fecha de fin no puede ser anterior o igual a la fecha de inicio."""
        event = Event(
            organizer=self.organizer,
            name="Festival de Jazz",
            description="Noche de improvisación y estándares de jazz.",
            category=Event.Category.CONCERT,
            start_date=self.start,
            end_date=self.start - timedelta(hours=1),
            location="Sala Principal",
            capacity=100,
            is_free=True,
            price=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("end_date", ctx.exception.message_dict)

    def test_reject_svg_upload_to_prevent_xss(self):
        """Bloquea subida de archivos SVG maliciosos (Stored XSS)."""
        svg_payload = SimpleUploadedFile(
            "exploit.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert("XSS")</script></svg>',
            content_type="image/svg+xml",
        )
        event = Event(
            organizer=self.organizer,
            name="Gala Lírica",
            description="Presentación especial de ópera y zarzuela.",
            category=Event.Category.OPERA,
            start_date=self.start,
            end_date=self.end,
            location="Sala Principal",
            capacity=200,
            is_free=False,
            price=Decimal("25.00"),
            image=svg_payload,
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("image", ctx.exception.message_dict)

from django.urls import reverse
from users.models import User


class EventPublicCatalogTests(TestCase):
    def setUp(self):
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

        # 1. Evento aprobado (visible en cartelera)
        self.PUBLISHED_concert = Event.objects.create(
            organizer=self.organizer,
            name="Noche de Boleros Sinfónicos",
            description="Un recorrido por los mejores boleros con orquesta en vivo.",
            category=Event.Category.SYMPHONIC,
            start_date=self.now + timedelta(days=5),
            end_date=self.now + timedelta(days=5, hours=2),
            location="Sala Principal",
            capacity=200,
            is_free=False,
            price=Decimal("25.00"),
            status=Event.Status.PUBLISHED,
        )

        # 2. Evento pendiente (oculto al público general)
        self.DRAFT_opera = Event.objects.create(
            organizer=self.organizer,
            name="La Traviata en Concierto",
            description="Versión de concierto de la célebre ópera de Giuseppe Verdi.",
            category=Event.Category.OPERA,
            start_date=self.now + timedelta(days=10),
            end_date=self.now + timedelta(days=10, hours=3),
            location="Sala Principal",
            capacity=150,
            is_free=False,
            price=Decimal("40.00"),
            status=Event.Status.DRAFT,
        )

    def test_home_catalog_shows_only_PUBLISHED_events(self):
        """La cartelera pública solo lista eventos en estado PUBLISHED."""
        response = self.client.get(reverse("events:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.PUBLISHED_concert.name)
        self.assertNotContains(response, self.DRAFT_opera.name)

    def test_catalog_search_and_category_filter(self):
        """El buscador por texto y el filtro por categoría devuelven coincidencias exactas."""
        Event.objects.create(
            organizer=self.organizer,
            name="Recital de Guitarra Quiteña",
            description="Música tradicional ecuatoriana interpretada en guitarra.",
            category=Event.Category.RECITAL,
            start_date=self.now + timedelta(days=3),
            end_date=self.now + timedelta(days=3, hours=2),
            location="Sala de Recitales",
            capacity=80,
            is_free=True,
            price=Decimal("0.00"),
            status=Event.Status.PUBLISHED,
        )

        # Búsqueda por nombre
        res_search = self.client.get(reverse("events:home"), {"q": "Guitarra"})
        self.assertContains(res_search, "Recital de Guitarra Quiteña")
        self.assertNotContains(res_search, "Noche de Boleros Sinfónicos")

        # Filtro por categoría
        res_cat = self.client.get(reverse("events:home"), {"category": Event.Category.SYMPHONIC})
        self.assertContains(res_cat, "Noche de Boleros Sinfónicos")
        self.assertNotContains(res_cat, "Recital de Guitarra Quiteña")

    def test_catalog_pagination(self):
        """La cartelera divide los resultados en páginas (6 eventos por página)."""
        for i in range(7):
            Event.objects.create(
                organizer=self.organizer,
                name=f"Concierto Cultural #{i + 1}",
                description="Evento cultural de prueba para validar la paginación.",
                category=Event.Category.CONCERT,
                start_date=self.now + timedelta(days=i + 1),
                end_date=self.now + timedelta(days=i + 1, hours=2),
                location="Sala Principal",
                capacity=100,
                is_free=True,
                price=Decimal("0.00"),
                status=Event.Status.PUBLISHED,
            )

        res_page_1 = self.client.get(reverse("events:home"))
        self.assertEqual(len(res_page_1.context["page_obj"]), 6)
        self.assertTrue(res_page_1.context["page_obj"].has_next())

        res_page_2 = self.client.get(reverse("events:home"), {"page": 2})
        self.assertEqual(len(res_page_2.context["page_obj"]), 2)  # 1 del setUp + 7 creados = 8 total

    def test_detail_view_hides_DRAFT_from_public_but_allows_organizer(self):
        """Un evento DRAFT da 404 a un cliente, pero su organizador sí puede previsualizarlo."""
        url_DRAFT = reverse("events:detail", kwargs={"pk": self.DRAFT_opera.pk})

        # Visitante anónimo o cliente normal recibe 404
        res_anon = self.client.get(url_DRAFT)
        self.assertEqual(res_anon.status_code, 404)

        self.client.force_login(self.client_user)
        res_client = self.client.get(url_DRAFT)
        self.assertEqual(res_client.status_code, 404)

        # El organizador dueño sí puede verlo
        self.client.force_login(self.organizer)
        res_org = self.client.get(url_DRAFT)
        self.assertEqual(res_org.status_code, 200)
        self.assertContains(res_org, self.DRAFT_opera.name)

class EventOrganizerCRUDAndSecurityTests(TestCase):
    def setUp(self):
        self.org_1 = User.objects.create_user(
            email="org1@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ORGANIZER,
        )
        self.org_2 = User.objects.create_user(
            email="org2@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ORGANIZER,
        )
        self.client_user = User.objects.create_user(
            email="cliente@epn.edu.ec",
            password="PasswordSegura123!",
            role=User.Role.CLIENT,
        )
        self.now = timezone.now()
        self.start_str = (self.now + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M")
        self.end_str = (self.now + timedelta(days=10, hours=2)).strftime("%Y-%m-%dT%H:%M")

        self.event_org_1 = Event.objects.create(
            organizer=self.org_1,
            name="Concierto de Cámara",
            description="Presentación de cuarteto de cuerdas en la sala de recitales.",
            category=Event.Category.RECITAL,
            start_date=self.now + timedelta(days=10),
            end_date=self.now + timedelta(days=10, hours=2),
            location="Sala de Recitales",
            capacity=100,
            available_tickets=100,
            is_free=False,
            price=Decimal("15.00"),
            status=Event.Status.PUBLISHED,
        )

    def test_client_cannot_access_organizer_views_rbac(self):
        """RBAC: Un usuario con rol CLIENT recibe 403 al intentar crear o listar como organizador."""
        self.client.force_login(self.client_user)
        res_list = self.client.get(reverse("events:org_list"))
        res_new = self.client.get(reverse("events:org_new"))
        self.assertEqual(res_list.status_code, 403)
        self.assertEqual(res_new.status_code, 403)

    def test_organizer_can_create_and_publish_event_directly(self):
        """Al crear un evento desde org_new, se asigna al organizador y se publica directamente (PUBLISHED)."""
        self.client.force_login(self.org_1)
        data = {
            "name": "Festival Coral Quiteño",
            "description": "Encuentro de coros polifónicos con repertorio ecuatoriano.",
            "category": Event.Category.CONCERT,
            "start_date": self.start_str,
            "end_date": self.end_str,
            "location": "Sala Principal",
            "capacity": 120,
            "is_free": True,
            "price": "0.00",
            "is_adult_only": False,
            "max_tickets_per_user": 2,
        }
        response = self.client.post(reverse("events:org_new"), data)
        self.assertEqual(response.status_code, 302)
        created = Event.objects.get(name="Festival Coral Quiteño")
        self.assertEqual(created.organizer, self.org_1)
        self.assertEqual(created.status, Event.Status.PUBLISHED)
        self.assertEqual(created.available_tickets, 120)

    def test_organizer_cannot_edit_delete_or_view_attendees_of_another_organizer_idor(self):
        """Seguridad IDOR: org_2 recibe 403 al intentar editar, borrar, cancelar o ver inscritos de org_1."""
        self.client.force_login(self.org_2)
        for route in ("events:edit", "events:delete", "events:attendees", "events:cancel"):
            url = reverse(route, kwargs={"pk": self.event_org_1.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_cannot_delete_event_with_sold_tickets_integrity(self):
        """Integridad: No se permite eliminar un evento que ya tiene entradas reservadas/vendidas."""
        # Simulamos que ya se vendieron 5 entradas (quedan 95 de 100)
        self.event_org_1.available_tickets = 95
        self.event_org_1.save()

        self.client.force_login(self.org_1)
        url = reverse("events:delete", kwargs={"pk": self.event_org_1.pk})
        response = self.client.post(url)
        # No debe borrarse de la base de datos
        self.assertTrue(Event.objects.filter(pk=self.event_org_1.pk).exists())
        self.assertEqual(response.status_code, 400)

    def test_organizer_can_delete_event_without_sold_tickets(self):
        """Si no se han vendido entradas (available_tickets == capacity), se elimina con confirmación."""
        self.client.force_login(self.org_1)
        url = reverse("events:delete", kwargs={"pk": self.event_org_1.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Event.objects.filter(pk=self.event_org_1.pk).exists())

import shutil
import tempfile
from django.test import TestCase, override_settings


class EventImageProcessingAndStorageTests(TestCase):
    def setUp(self):
        # Directorio temporal aislado que se destruye automáticamente al terminar cada test
        self.temp_media = tempfile.mkdtemp()
        self.override = override_settings(
            MEDIA_ROOT=self.temp_media,
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                },
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                },
            },
        )
        self.override.enable()

        self.organizer = User.objects.create_user(
            email="org_img@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ORGANIZER,
        )
        self.now = timezone.now()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_uploaded_jpeg_is_sanitized_resized_and_converted_to_webp(self):
        """
        Seguridad y rendimiento: al guardar un evento con una imagen grande (2000x2000 JPG),
        se sanitiza, se redimensiona a máximo 1600x1600 y se almacena optimizada en formato WEBP.
        """
        buf = BytesIO()
        large_img = Image.new("RGB", (2000, 2000), color=(25, 80, 160))
        large_img.save(buf, format="JPEG")
        buf.seek(0)
        uploaded_jpg = SimpleUploadedFile(
            "afiche_original.jpg", buf.read(), content_type="image/jpeg"
        )

        event = Event.objects.create(
            organizer=self.organizer,
            name="Gala Sinfónica con Afiche",
            description="Prueba de sanitización y optimización automática de imagen.",
            category=Event.Category.SYMPHONIC,
            start_date=self.now + timedelta(days=5),
            end_date=self.now + timedelta(days=5, hours=2),
            location="Sala Principal",
            capacity=100,
            is_free=True,
            price=Decimal("0.00"),
            image=uploaded_jpg,
        )

        # 1. El nombre guardado debe terminar en .webp y generar URL válida
        self.assertTrue(event.image.name.endswith(".webp"))
        self.assertTrue(event.image.url.endswith(".webp"))

        # 2. Al abrir el archivo almacenado, su formato real debe ser WEBP y <= 1600x1600
        with Image.open(event.image.path) as stored_img:
            self.assertEqual(stored_img.format, "WEBP")
            self.assertLessEqual(stored_img.width, 1600)
            self.assertLessEqual(stored_img.height, 1600)

    def test_reject_oversized_image_above_2mb_dos_prevention(self):
        """Seguridad (DoS): rechaza archivos de imagen que superen el límite de 2 MB."""
        # Simulamos un payload superior a 2 MB (2.1 MB)
        oversized_file = SimpleUploadedFile(
            "pesada.jpg",
            b"\xff\xd8\xff\xe0" + (b"0" * (2 * 1024 * 1024 + 102400)),
            content_type="image/jpeg",
        )

        event = Event(
            organizer=self.organizer,
            name="Evento con Imagen Pesada",
            description="Prueba de rechazo por límite de tamaño de archivo.",
            category=Event.Category.CONCERT,
            start_date=self.now + timedelta(days=6),
            end_date=self.now + timedelta(days=6, hours=2),
            location="Sala Principal",
            capacity=100,
            is_free=True,
            price=Decimal("0.00"),
            image=oversized_file,
        )

        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("image", ctx.exception.message_dict)

class EventModerationTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            email="admin@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ADMIN,
        )
        self.organizer = User.objects.create_user(
            email="org@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ORGANIZER,
        )
        self.other_organizer = User.objects.create_user(
            email="otro_org@casadelamusica.ec",
            password="PasswordSegura123!",
            role=User.Role.ORGANIZER,
        )
        self.now = timezone.now()
        self.published_event = Event.objects.create(
            organizer=self.organizer,
            name="Gala de Bandoneón",
            description="Concierto especial de tango y música rioplatense en vivo.",
            category=Event.Category.CONCERT,
            start_date=self.now + timedelta(days=8),
            end_date=self.now + timedelta(days=8, hours=2),
            location="Sala Principal",
            capacity=180,
            is_free=False,
            price=Decimal("20.00"),
            status=Event.Status.PUBLISHED,
        )
        self.draft_event = Event.objects.create(
            organizer=self.organizer,
            name="Ensayo Sinfónico en Borrador",
            description="Evento en borrador que no debe aparecer como publicado vigente.",
            category=Event.Category.SYMPHONIC,
            start_date=self.now + timedelta(days=12),
            end_date=self.now + timedelta(days=12, hours=2),
            location="Sala Principal",
            capacity=100,
            is_free=True,
            price=Decimal("0.00"),
            status=Event.Status.DRAFT,
        )

    def test_organizer_cannot_access_moderation_views_rbac(self):
        """Seguridad: Un organizador no puede entrar al panel administrativo de moderación ni cancelar eventos ajenos (403)."""
        self.client.force_login(self.other_organizer)
        res_queue = self.client.get(reverse("events:moderation_list"))
        res_cancel_other = self.client.post(
            reverse("events:cancel", kwargs={"pk": self.published_event.pk})
        )
        self.assertEqual(res_queue.status_code, 403)
        self.assertEqual(res_cancel_other.status_code, 403)

    def test_admin_moderation_list_displays_active_published_events(self):
        """El panel de administrador lista los eventos publicados vigentes con opciones de ver detalles y cancelar."""
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("events:moderation_list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.published_event.name)
        self.assertNotContains(res, self.draft_event.name)
        self.assertContains(res, reverse("events:detail", kwargs={"pk": self.published_event.pk}))
        self.assertContains(res, reverse("events:cancel", kwargs={"pk": self.published_event.pk}))

    def test_admin_can_cancel_published_event(self):
        """El administrador puede cancelar un evento publicado vigente; pasa a CANCELLED y sale de cartelera."""
        self.client.force_login(self.admin_user)
        url = reverse("events:cancel", kwargs={"pk": self.published_event.pk})

        # GET muestra la plantilla de confirmación de cancelación
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, self.published_event.name)

        # POST ejecuta la cancelación
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.published_event.refresh_from_db()
        self.assertEqual(self.published_event.status, Event.Status.CANCELLED)
        self.assertEqual(self.published_event.moderated_by, self.admin_user)

        # Ya no aparece en la cartelera pública
        res_home = self.client.get(reverse("events:home"))
        self.assertNotContains(res_home, self.published_event.name)

    def test_organizer_can_cancel_own_published_event(self):
        """El organizador dueño también puede cancelar su propio evento publicado."""
        # Simulamos que el evento ya tiene una imagen guardada en Cloudinary (public_id sin extensión)
        Event.objects.filter(pk=self.published_event.pk).update(
            image="media/events/2026/11/afiche_cloudinary_id"
        )
        self.client.force_login(self.organizer)
        url = reverse("events:cancel", kwargs={"pk": self.published_event.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.published_event.refresh_from_db()
        self.assertEqual(self.published_event.status, Event.Status.CANCELLED)
