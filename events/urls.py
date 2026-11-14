from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    path('', views.home, name='home'),
    path('<uuid:pk>/', views.detail, name='detail'),
    path('mis_eventos/', views.org_list, name='org_list'),
    path('nuevo/', views.org_new, name='org_new'),
    path('<uuid:pk>/editar/', views.event_edit, name='edit'),
    path('<uuid:pk>/eliminar/', views.event_delete, name='delete'),
    path('<uuid:pk>/asistentes/', views.event_attendees, name='attendees'),
]
