from django.urls import path

from . import views

app_name = 'tickets'

urlpatterns = [
    path('comprar/<uuid:event_id>/', views.pay, name='pay'),
    path('cancelar/', views.cancel, name='cancel'),
    path('ok/', views.ok, name='ok'),
    path('', views.my_tickets, name='tickets'),
    path('estado/', views.reservation_status, name='reservation_status'),
    path('escanear/', views.scan, name='scan'),
    path('validaciones/', views.validation_history, name='validation_history'),
    path('api/validar/', views.validate_ticket_api, name='validate'),
    path('webhooks/stripe/', views.stripe_webhook, name='stripe_webhook'),
    path('<uuid:pk>/', views.ticket_detail, name='tk'),
    path('<uuid:pk>/qr/', views.ticket_qr, name='qr'),
]
