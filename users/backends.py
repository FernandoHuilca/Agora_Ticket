from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model


class AccountBackend(ModelBackend):
    """Aplica suspensión al login y al recuperar usuarios desde su sesión."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        # username es el nombre interno que emplean formularios como el del admin.
        identifier = email if email is not None else username
        if not identifier or password is None:
            return None
        model = get_user_model()
        try:
            user = model.objects.get(email__iexact=identifier.strip())
        except (model.DoesNotExist, model.MultipleObjectsReturned):
            # No elegir una cuenta arbitraria si hay correos antiguos ambiguos.
            model().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

