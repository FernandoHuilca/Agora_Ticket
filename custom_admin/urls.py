from django.urls import path
from . import views

app_name = 'custom_admin'

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('usuarios/<int:user_id>/toggle/', views.toggle_estado_usuario, name='toggle_estado_usuario'),
]