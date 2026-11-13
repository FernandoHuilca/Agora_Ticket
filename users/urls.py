from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .forms import AccountPasswordResetForm, AccountSetPasswordForm

from .views import AccountLoginView, dashboard, profile, register

app_name = 'users'

urlpatterns = [
    path('registro/', register, name='register'),
    path('login/', AccountLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('panel/', dashboard, name='dashboard'),
    path('perfil/', profile, name='profile'),

    # Django genera el token, comprueba su caducidad y guarda la nueva contraseña.
    path('recuperar/', auth_views.PasswordResetView.as_view(
        form_class=AccountPasswordResetForm,
        template_name='users/password_reset_form.html',
        email_template_name='users/email/password_reset.txt',
        html_email_template_name='users/email/password_reset.html',
        subject_template_name='users/email/password_reset_subject.txt',
        success_url=reverse_lazy('users:password_reset_done'),
    ), name='password_reset'),
    path('recuperar/enviado/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_status.html',
        extra_context={
            'heading': 'Revisa tu correo',
            'description': 'Si existe una cuenta habilitada asociada a ese correo, recibirás un enlace. Revisa también el correo no deseado. El enlace caduca en una hora.',
            'allow_retry': True,
        },
    ), name='password_reset_done'),
    path('restablecer/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        form_class=AccountSetPasswordForm,
        template_name='users/password_reset_confirm.html',
        success_url=reverse_lazy('users:password_reset_complete'),
    ), name='password_reset_confirm'),
    path('restablecer/completado/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_status.html',
        extra_context={
            'heading': 'Contraseña actualizada',
            'description': 'Ya puedes entrar con tu correo y tu nueva contraseña.',
        },
    ), name='password_reset_complete'),
]
