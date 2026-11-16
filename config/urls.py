from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from django.views.defaults import permission_denied

from events import views as event_views

admin.site.site_header = "Ágora Ticket - Administración Técnica"
admin.site.site_title = "Ágora Ticket Admin"
admin.site.index_title = "Gestión de Base de Datos"

urlpatterns = [
    # La portada del sitio es la cartelera pública de eventos.
    path('', event_views.home, name='home'),
    path('', include('users.urls')),
    path('admin/', admin.site.urls),
    path('dashboard/', include('custom_admin.urls')),
    path('eventos/', include('events.urls')),
    path('tickets/', include('tickets.urls')),
]

if settings.DEBUG:
    urlpatterns += [
        path('403/', permission_denied, {'exception': None}),
    ]
