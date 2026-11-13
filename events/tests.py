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

    def test_create_valid_event_initializes_available_tickets(self):
        """Al crear un evento válido, available_tickets se inicializa igual a capacity."""
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
        self.assertEqual(event.status, Event.Status.PENDING)

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