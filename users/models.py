from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El correo electrónico es obligatorio.')
        user = self.model(email=email.strip().lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        if not extra_fields['is_staff'] or not extra_fields['is_superuser']:
            raise ValueError('El superusuario debe tener is_staff e is_superuser activos.')
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    """Identidad compartida por todos los módulos del monolito."""

    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrador'
        ORGANIZER = 'organizer', 'Organizador'
        CLIENT = 'client', 'Cliente'
        SCANNER = 'scanner', 'Escaneador'

    ROLE_CHOICES = Role.choices
    username = None
    email = models.EmailField(unique=True)
    date_of_birth = models.DateField(
        'Fecha de nacimiento', null=True, blank=True,
        validators=[MaxValueValidator(timezone.localdate)],
    )
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    objects = UserManager()
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=Role.CLIENT)

    @property
    def can_access_platform(self):
        """Estado de cuenta requerido para cualquier operación privada."""
        return self.is_active

    def has_role(self, *roles):
        """Comprueba roles explícitos sin conceder privilegios implícitos."""
        return self.can_access_platform and self.role in roles

    def __str__(self):
        return f"{self.email} ({self.role})"
