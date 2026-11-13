import unicodedata

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm, UserCreationForm
from django.utils import timezone

from .models import User

PASSWORD_GUIDANCE = (
    '<ul>'
    '<li>Debe contener al menos 8 caracteres.</li>'
    '<li>No puede contener únicamente números.</li>'
    '</ul>'
)


class NameField(forms.CharField):
    def __init__(self, **kwargs):
        super().__init__(max_length=100, **kwargs)

    def clean(self, value):
        value = super().clean(unicodedata.normalize('NFC', value or ''))
        if any(not (character.isalpha() or character == ' ') for character in value):
            raise forms.ValidationError('Solo se permiten letras y espacios, incluidas tildes y ñ.')
        return value


class BirthDateWidget(forms.SelectDateWidget):
    def get_context(self, name, value, attrs):
        # Mostrar opciones vacías sin quitar la validación obligatoria del campo.
        required = self.is_required
        self.is_required = False
        try:
            return super().get_context(name, value, attrs)
        finally:
            self.is_required = required


class AccountSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].help_text = PASSWORD_GUIDANCE
        self.fields['new_password2'].label = 'Repetir contraseña'
        self.fields['new_password2'].help_text = ''


class AccountPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        # Igual que el login: no seleccionar cuentas con correos ambiguos.
        users = list(User.objects.filter(email__iexact=email.strip()))
        if len(users) != 1:
            return []
        user = users[0]
        return [user] if user.can_access_platform and user.has_usable_password() else []


class EmailAuthenticationForm(forms.Form):
    email = forms.EmailField(
        label='Correo electrónico', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}),
    )
    password = forms.CharField(
        label='Contraseña', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email, password = cleaned.get('email'), cleaned.get('password')
        if email and password:
            self.user_cache = authenticate(self.request, email=email, password=password)
            if self.user_cache is None:
                raise forms.ValidationError('Correo electrónico o contraseña incorrectos.')
        return cleaned

    def get_user(self):
        return self.user_cache


class RegistrationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].help_text = PASSWORD_GUIDANCE
        self.fields['password2'].label = 'Repetir contraseña'
        self.fields['password2'].help_text = ''

    first_name = NameField(label='Nombres', error_messages={'max_length': 'Los nombres no pueden superar los 100 caracteres.'})
    last_name = NameField(label='Apellidos', error_messages={'max_length': 'Los apellidos no pueden superar los 100 caracteres.'})
    date_of_birth = forms.DateField(
        label='Fecha de nacimiento',
        widget=BirthDateWidget(
            years=range(timezone.localdate().year, 1899, -1),
            empty_label=('Año', 'Mes', 'Día'),
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('first_name', 'last_name', 'email', 'date_of_birth')
        labels = {'email': 'Correo electrónico'}

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con este correo electrónico.')
        return email


class ProfileForm(forms.ModelForm):
    first_name = NameField(label='Nombres', error_messages={'max_length': 'Los nombres no pueden superar los 100 caracteres.'})
    last_name = NameField(label='Apellidos', error_messages={'max_length': 'Los apellidos no pueden superar los 100 caracteres.'})
    date_of_birth = forms.DateField(
        label='Fecha de nacimiento',
        widget=BirthDateWidget(
            years=range(timezone.localdate().year, 1899, -1),
            empty_label=('Año', 'Mes', 'Día'),
        ),
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'date_of_birth')
        labels = {
            'email': 'Correo electrónico',
        }

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe una cuenta con este correo electrónico.')
        return email
