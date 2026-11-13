from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView
from django.views.defaults import permission_denied

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='users:login', permanent=False), name='home'),
    path('', include('users.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += [
        path('403/', permission_denied, {'exception': None}),
    ]
