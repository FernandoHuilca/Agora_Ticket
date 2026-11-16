import os
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'clave-temporal-desarrollo-agora-ticket')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
RESERVATION_HOLD_MINUTES = int(os.getenv('RESERVATION_HOLD_MINUTES', '30'))
TICKETS_MAX_PER_PURCHASE = int(os.getenv('TICKETS_MAX_PER_PURCHASE', '10'))
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8000').rstrip('/')

TICKET_QR_SECRET = os.getenv('TICKET_QR_SECRET')
if not TICKET_QR_SECRET:
    if DEBUG:
        TICKET_QR_SECRET = 'dev-only-ticket-qr-secret-change-me'
    else:
        raise ImproperlyConfigured(
            'TICKET_QR_SECRET debe estar configurado cuando DEBUG=False.'
        )

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'channels',
    # Módulos de Ágora Ticket
    'users',
    'events',
    'tickets',
    'chat',
    'custom_admin',
    # Aplicaciones de terceros
    'cloudinary_storage',
    'cloudinary',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Channel layer de Django Channels: reparte los mensajes entre conexiones WebSocket.
# Sin REDIS_URL se usa la capa en memoria, válida mientras la app corra en UN solo
# proceso (desarrollo y un único servicio en Render). Con REDIS_URL se usa Redis,
# necesario si se escala a varios procesos o instancias.
REDIS_URL = os.getenv('REDIS_URL', '').strip()
if REDIS_URL and 'test' not in sys.argv:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
        'OPTIONS': {
            'sslmode': os.getenv('DB_SSLMODE', 'require'),
        },
    }
}
# Usar SQLite en memoria solo para ejecutar pruebas
if 'test' in sys.argv:
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }

AUTH_USER_MODEL = 'users.User'
AUTHENTICATION_BACKENDS = ['users.backends.AccountBackend']
LOGIN_URL = 'users:login'
LOGIN_REDIRECT_URL = 'users:dashboard'
LOGOUT_REDIRECT_URL = 'users:login'

PASSWORD_RESET_TIMEOUT = 60 * 60
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Agora Ticket <no-reply@example.com>')
MAILERS = {
    'default': {
        'BACKEND': os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'),
    },
}
if MAILERS['default']['BACKEND'] == 'django.core.mail.backends.smtp.EmailBackend':
    MAILERS['default']['OPTIONS'] = {
        'host': os.getenv('EMAIL_HOST', ''),
        'port': int(os.getenv('EMAIL_PORT', '587')),
        'username': os.getenv('EMAIL_HOST_USER', ''),
        'password': os.getenv('EMAIL_HOST_PASSWORD', ''),
        'use_tls': os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true',
        'use_ssl': os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true',
        'timeout': 15,
    }

# Sesiones persistidas en la base de datos, con cierre al salir del navegador.
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 60 * 60 * 2
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'CSRF_TRUSTED_ORIGINS',
        'https://agora-ticket.onrender.com,http://localhost:8000,http://127.0.0.1:8000',
    ).split(',')
    if origin.strip()
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ec'
TIME_ZONE = 'America/Guayaquil'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Configuración de almacenamiento en la nube (Cloudinary) o local según variable de entorno

CLOUDINARY_URL = os.getenv('CLOUDINARY_URL', '')

if CLOUDINARY_URL:
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': os.getenv('CLOUDINARY_CLOUD_NAME'),
        'API_KEY': os.getenv('CLOUDINARY_API_KEY'),
        'API_SECRET': os.getenv('CLOUDINARY_API_SECRET'),
        'SECURE': True,  # Fuerza URLs con HTTPS
    }
    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
else:
    # Desarrollo local y ejecución de pruebas (python manage.py test)
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }