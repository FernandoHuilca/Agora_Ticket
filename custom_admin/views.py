from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages

User = get_user_model()

# Función que verifica que el usuario sea Administrador (staff o superuser)
def es_administrador(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)

@user_passes_test(es_administrador, login_url='/admin/login/')
def dashboard_home(request):
    # Métricas reales desde la tabla users_user en Neon
    total_usuarios = User.objects.count()
    usuarios_activos = User.objects.filter(is_active=True).count()
    usuarios_bloqueados = User.objects.filter(is_active=False).count()
    total_admins = User.objects.filter(is_staff=True).count()

    # Lista de los últimos 10 usuarios registrados para moderación
    ultimos_usuarios = User.objects.all().order_by('-date_joined')[:10]

    context = {
        'total_usuarios': total_usuarios,
        'usuarios_activos': usuarios_activos,
        'usuarios_bloqueados': usuarios_bloqueados,
        'total_admins': total_admins,
        'ultimos_usuarios': ultimos_usuarios,
        # Métricas listas para conectarse cuando Eventos y Tickets hagan merge
        'total_eventos': 0,
        'tickets_vendidos': 0,
    }
    return render(request, 'custom_admin/dashboard.html', context)

@user_passes_test(es_administrador, login_url='/admin/login/')
def toggle_estado_usuario(request, user_id):
    if request.method == 'POST':
        usuario = get_object_or_404(User, id=user_id)
        # Evitar que el administrador se bloquee a sí mismo por error
        if usuario == request.user:
            messages.error(request, "No puedes desactivar tu propia cuenta de administrador.")
        else:
            usuario.is_active = not usuario.is_active
            usuario.save()
            estado = "activado" if usuario.is_active else "bloqueado"
            messages.success(request, f"El usuario {usuario.username} ha sido {estado}.")
    return redirect('custom_admin:dashboard_home')