from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('<uuid:pk>/', views.inbox, name='conversation'),
    path('<uuid:pk>/historial/', views.history, name='history'),
    path('evento/<uuid:event_id>/', views.open_event, name='open_event'),
    path('evento/<uuid:event_id>/sala/', views.open_general, name='open_general'),
    path(
        'evento/<uuid:event_id>/comprador/<int:user_id>/',
        views.open_with_buyer,
        name='open_with_buyer',
    ),
]
