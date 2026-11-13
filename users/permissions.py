"""Comprobaciones comunes; cada módulo debe validar también la propiedad."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User


def role_required(*roles):
    """Redirige visitantes al login y rechaza cuentas sin autorización con 403."""
    if not roles or any(role not in User.Role.values for role in roles):
        raise ValueError('Especifica al menos un rol válido de User.Role.')

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.has_role(*roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
