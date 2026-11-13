from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .forms import EmailAuthenticationForm, ProfileForm, RegistrationForm


def register(request):
    if request.user.is_authenticated:
        return redirect('users:dashboard')

    form = RegistrationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Cuenta creada. Ya puedes iniciar sesión.')
        return redirect('users:login')

    return render(request, 'users/register.html', {'form': form})


class AccountLoginView(LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = 'users/login.html'
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    return render(request, 'users/dashboard.html')


@login_required
def profile(request):
    # La cuenta se obtiene de la sesión, nunca de un ID enviado por el usuario.
    form = ProfileForm(
        request.POST if request.method == 'POST' else None,
        instance=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Perfil actualizado correctamente.')
        return redirect('users:profile')

    return render(request, 'users/profile.html', {'form': form})
