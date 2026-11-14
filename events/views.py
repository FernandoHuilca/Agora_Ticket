from functools import wraps
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from users.models import User
from .forms import EventFilterForm, EventForm
from .models import Event

try:
    from users.permissions import role_required
except ImportError:
    def role_required(*allowed_roles):
        def decorator(view_func):
            @wraps(view_func)
            def _wrapped(request, *args, **kwargs):
                if not request.user.is_authenticated:
                    return redirect_to_login(request.get_full_path())
                if not request.user.is_active or request.user.role not in allowed_roles:
                    raise PermissionDenied("No tienes permisos para acceder a esta sección.")
                return view_func(request, *args, **kwargs)
            return _wrapped
        return decorator


def _check_event_ownership_or_admin(user, event):
    """Garantiza en el servidor que solo el organizador dueño o un ADMIN operen el evento (Anti-IDOR)."""
    is_admin = hasattr(user, 'has_role') and user.has_role(User.Role.ADMIN)
    if event.organizer_id != user.id and not is_admin:
        raise PermissionDenied("No tienes permiso para gestionar un evento de otro organizador.")


def home(request):
    """Vista 'home': Cartelera pública de eventos aprobados con búsqueda, filtros y paginación."""
    queryset = Event.objects.filter(
        status=Event.Status.PUBLISHED
    ).select_related('organizer').order_by('start_date')

    filter_form = EventFilterForm(request.GET or None)
    if filter_form.is_valid():
        q = filter_form.cleaned_data.get('q')
        category = filter_form.cleaned_data.get('category')
        date_from = filter_form.cleaned_data.get('date_from')
        is_free = filter_form.cleaned_data.get('is_free')

        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) |
                Q(description__icontains=q) |
                Q(location__icontains=q)
            )
        if category:
            queryset = queryset.filter(category=category)
        if date_from:
            queryset = queryset.filter(start_date__date__gte=date_from)
        if is_free in ('0', '1'):
            queryset = queryset.filter(is_free=(is_free == '1'))

    paginator = Paginator(queryset, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'events/event_list.html', {
        'page_obj': page_obj,
        'filter_form': filter_form,
    })


def detail(request, pk):
    """Vista 'detail': Detalle de un evento."""
    event = get_object_or_404(Event.objects.select_related('organizer'), pk=pk)

    if event.status != Event.Status.PUBLISHED:
        user = request.user
        is_owner = user.is_authenticated and event.organizer_id == user.id
        is_admin = user.is_authenticated and hasattr(user, 'has_role') and user.has_role(User.Role.ADMIN)
        if not (is_owner or is_admin):
            raise Http404("El evento solicitado no está disponible públicamente.")

    return render(request, 'events/event_detail.html', {'event': event})


@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def org_list(request):
    """Vista 'orgList': Listado paginado de eventos del organizador actual (con filtro por estado)."""
    if request.user.has_role(User.Role.ADMIN):
        queryset = Event.objects.all().select_related('organizer').order_by('-created_at')
    else:
        queryset = Event.objects.filter(organizer=request.user).order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter in Event.Status.values:
        queryset = queryset.filter(status=status_filter)

    paginator = Paginator(queryset, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'events/org_list.html', {
        'page_obj': page_obj,
        'status_choices': Event.Status.choices,
        'current_status': status_filter or '',
    })


@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def org_new(request):
    """
    Vista 'orgNew': Creación y publicación directa de un evento por el organizador.
    Dispara una notificación en tiempo real hacia Django Channels al publicarse.
    """
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.organizer = request.user
            event.status = Event.Status.PUBLISHED
            event.available_tickets = form.cleaned_data['capacity']
            event.save()

            # Notificar en tiempo real a través de WebSockets (coordina con Persona 4)
            _broadcast_new_event_notification(event)

            messages.success(request, 'Evento creado y publicado en la cartelera exitosamente.')
            return redirect('events:org_list')
    else:
        form = EventForm()

    return render(request, 'events/event_form.html', {
        'form': form,
        'is_edit': False,
    })


@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def event_edit(request, pk):
    """Edición de un evento existente verificando propiedad del organizador."""
    event = get_object_or_404(Event, pk=pk)
    _check_event_ownership_or_admin(request.user, event)

    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, 'Información del evento actualizada.')
            return redirect('events:org_list')
    else:
        form = EventForm(instance=event)

    return render(request, 'events/event_form.html', {
        'form': form,
        'event': event,
        'is_edit': True,
    })


@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def event_delete(request, pk):
    """Eliminación con confirmación e integridad (impide borrar si ya hay entradas emitidas)."""
    event = get_object_or_404(Event, pk=pk)
    _check_event_ownership_or_admin(request.user, event)

    tickets_sold = event.capacity - event.available_tickets

    if request.method == 'POST':
        if tickets_sold > 0:
            return HttpResponseBadRequest(
                "No se puede eliminar un evento que ya tiene entradas vendidas o reservadas."
            )
        event.delete()
        messages.success(request, 'El evento ha sido eliminado.')
        return redirect('events:org_list')

    return render(request, 'events/event_confirm_delete.html', {
        'event': event,
        'tickets_sold': tickets_sold,
    })


@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def event_attendees(request, pk):
    """Consulta de usuarios inscritos/compradores del evento (conecta con el modelo Ticket de P3)."""
    event = get_object_or_404(Event, pk=pk)
    _check_event_ownership_or_admin(request.user, event)

    # Si Persona 3 ya migró el modelo Ticket con related_name='tickets', lo consultamos;
    # de lo contrario, devolvemos lista vacía sin romper la vista.
    tickets_qs = getattr(event, 'tickets', None)
    attendees = tickets_qs.select_related('user').all() if tickets_qs is not None else []
    tickets_sold = event.capacity - event.available_tickets

    return render(request, 'events/event_attendees.html', {
        'event': event,
        'attendees': attendees,
        'tickets_sold': tickets_sold,
    })

def _broadcast_new_event_notification(event):
    """
    Envía una notificación en tiempo real por Django Channels cuando un evento es publicado.
    Coordina con Persona 4 (grupo 'notifications').
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                "notifications",
                {
                    "type": "event_notification",
                    "event_id": str(event.pk),
                    "name": event.name,
                    "category": event.get_category_display(),
                    "start_date": event.start_date.strftime("%d/%m/%Y %H:%M"),
                    "message": f"Nuevo evento publicado en cartelera: {event.name}",
                },
            )
    except Exception:
        # Si Redis/Channels aún no está levantado en local, no interrumpir la transacción HTTP
        pass


@role_required(User.Role.ADMIN)
def moderation_list(request):
    """
    Panel de administración de eventos: Lista eventos publicados vigentes por defecto
    para que el administrador pueda consultar sus detalles o cancelarlos en caso de incidente.
    """
    status_filter = request.GET.get('status', Event.Status.PUBLISHED)
    if status_filter not in Event.Status.values:
        status_filter = Event.Status.PUBLISHED

    queryset = Event.objects.filter(
        status=status_filter
    ).select_related('organizer', 'moderated_by')

    if status_filter == Event.Status.PUBLISHED:
        queryset = queryset.filter(end_date__gte=timezone.now()).order_by('start_date')
    else:
        queryset = queryset.order_by('-created_at')

    paginator = Paginator(queryset, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'events/moderation_list.html', {
        'page_obj': page_obj,
        'current_status': status_filter,
        'status_choices': Event.Status.choices,
    })


@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def event_cancel(request, pk):
    """Permite al organizador dueño o al ADMIN cancelar un evento publicado."""
    event = get_object_or_404(Event.objects.select_related('organizer'), pk=pk)
    _check_event_ownership_or_admin(request.user, event)

    if request.method == 'POST':
        event.status = Event.Status.CANCELLED
        event.moderated_by = request.user
        event.save(update_fields=['status', 'moderated_by', 'updated_at'])
        messages.warning(request, f'El evento "{event.name}" ha sido cancelado.')
        if hasattr(request.user, 'has_role') and request.user.has_role(User.Role.ADMIN):
            return redirect('events:moderation_list')
        return redirect('events:org_list')

    return render(request, 'events/event_confirm_cancel.html', {'event': event})
