from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.db.models import F, Q, Sum
from django.utils import timezone

from events.models import Event

User = get_user_model()


# Función que verifica que el usuario sea Administrador (rol de negocio 'admin', staff o superuser)
def es_administrador(user):
    if not user.is_authenticated or not user.is_active:
        return False
    es_admin_negocio = hasattr(user, 'has_role') and user.has_role(User.Role.ADMIN)
    return es_admin_negocio or user.is_staff or user.is_superuser


@user_passes_test(es_administrador, login_url='users:login')
def dashboard_home(request):
    # Métricas reales desde la tabla users_user
    total_usuarios = User.objects.count()
    usuarios_activos = User.objects.filter(is_active=True).count()
    usuarios_bloqueados = User.objects.filter(is_active=False).count()
    total_admins = User.objects.filter(
        Q(role=User.Role.ADMIN) | Q(is_staff=True) | Q(is_superuser=True)
    ).distinct().count()

    # Lista de los últimos 10 usuarios registrados para moderación
    ultimos_usuarios = User.objects.all().order_by('-date_joined')[:10]

    # Eventos publicados vigentes conectados desde el módulo events
    eventos_vigentes_qs = Event.objects.filter(
        status=Event.Status.PUBLISHED,
        end_date__gte=timezone.now(),
    ).select_related('organizer').order_by('start_date')

    total_eventos = eventos_vigentes_qs.count()
    tickets_vendidos = (
        Event.objects.aggregate(
            vendidos=Sum(F('capacity') - F('available_tickets'))
        )['vendidos']
        or 0
    )

    context = {
        'total_usuarios': total_usuarios,
        'usuarios_activos': usuarios_activos,
        'usuarios_bloqueados': usuarios_bloqueados,
        'total_admins': total_admins,
        'ultimos_usuarios': ultimos_usuarios,
        'total_eventos': total_eventos,
        'tickets_vendidos': tickets_vendidos,
        'eventos_vigentes': eventos_vigentes_qs[:10],
    }
    return render(request, 'custom_admin/dashboard.html', context)


@user_passes_test(es_administrador, login_url='users:login')
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
            identificador = usuario.username or usuario.email
            messages.success(request, f"El usuario {identificador} ha sido {estado}.")
    return redirect('custom_admin:dashboard_home')
