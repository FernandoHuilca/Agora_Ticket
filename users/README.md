# Usuarios y autenticación — primer bimestre

## Cómo está organizado

| Archivo | Para qué sirve |
| --- | --- |
| models.py | Usuario, roles y estado de la cuenta. |
| forms.py | Validación del registro, login por correo y selección de cuentas para recuperación. |
| backends.py | Comprueba correo y contraseña; rechaza cuentas suspendidas o inactivas. |
| views.py | Registro, configuración del login de Django y panel privado. |
| urls.py | Rutas, incluyendo las vistas de recuperación que ya proporciona Django. |
| permissions.py | Decorador para proteger vistas según el rol. |
| templates/users/ | Pantallas y contenido del correo. |

## Ejecutar y usar

Con el entorno virtual y el .env de base de datos configurados:

```powershell
python manage.py runserver
```

- `/` redirige a `/login/`.
- `/registro/` crea una cuenta cliente; `/login/` usa correo y contraseña.
- `/panel/` requiere sesión; cerrar sesión envía POST a `/logout/` con CSRF.
- `/perfil/` permite editar nombres, apellidos, correo y fecha de nacimiento.
  Rechaza correos utilizados por otra cuenta, sin distinguir mayúsculas.
  El rol se muestra solo para consulta; no se aceptan privilegios desde el formulario.
  Nombres y apellidos admiten hasta 100 caracteres en registro y perfil. El navegador
  bloquea caracteres adicionales y muestra un aviso al alcanzar el límite;
  Django también rechaza valores superiores antes de guardar.
- `/recuperar/` solicita un enlace; `/restablecer/<uidb64>/<token>/` permite cambiar
  la contraseña. Caduca en una hora y queda invalidado al cambiar la contraseña.

Se usa `users.User`, basado en `AbstractUser`, sin campo username. El correo es el
identificador de acceso. Registro pide nombres, apellidos, correo, fecha de nacimiento,
contraseña y confirmación. Rechaza fechas futuras; no exige ser mayor de edad para
crear una cuenta. La validación de edad por evento corresponde a eventos y tickets.
Las cuentas existentes conservan sus IDs y pueden completar su fecha en el perfil.
La migración `0002_email_login_date_of_birth` elimina la columna username y agrega
la fecha de nacimiento; ejecutar `python manage.py migrate` antes de usar el módulo.
Coordinar su aplicación con Persona 5 si la base de datos es compartida. Registro
normaliza el correo y rechaza duplicados ignorando mayúsculas. La restricción de
base de datos todavía es exacta: una futura migración debe cubrir también la
unicidad sin mayúsculas para escrituras concurrentes o externas al formulario.

## Roles y permisos para acordar con Persona 5

Cada cuenta tiene un solo rol. Visitante es alguien sin sesión, no un rol guardado.

| Rol | Acceso de negocio previsto |
| --- | --- |
| client | Entradas propias, perfil y chat. |
| organizer | Lo anterior y gestión de eventos propios e inscritos. |
| scanner | Funciones personales y validación en eventos asignados. |
| admin | Administración de usuarios, roles, eventos, moderación y auditoría. |

Cartelera publicada será pública; el panel es privado. Los cuatro roles pueden
adquirir entradas personales. Confirmar esta política con Persona 5 y la asignación
de escaneadores con Persona 3. Eliminar eventos debe respetar reglas de integridad.

`is_staff` e `is_superuser` son privilegios técnicos de Django; no equivalen al
rol `admin`. No hay jerarquía implícita en `has_role`: cada vista declara sus roles.

```python
from users.models import User
from users.permissions import role_required

@role_required(User.Role.ORGANIZER, User.Role.ADMIN)
def editar_evento(request, event_id):
    # Persona 2 debe comprobar además que el evento pertenece al organizador.
    ...
```

Persona 5 gestiona roles y suspensión desde su panel. Los formularios públicos no
deben aceptar roles, suspensión ni privilegios técnicos. Los otros módulos deben
relacionarse con `settings.AUTH_USER_MODEL` y aplicar sus controles de propiedad.
Persona 4 debe autenticar WebSocket y gestionar la suspensión en conexiones abiertas.
El decorador protege vistas HTTP síncronas, no conexiones WebSocket.

## Sesiones y contraseñas

El estado se controla únicamente con `is_active`: True habilita la cuenta y False
la suspende. Se conservan `is_staff` e `is_superuser` para la administración técnica
de Django. La migración `0003_remove_is_suspended` desactiva primero las cuentas
que tenían `is_suspended=True` y después elimina esa columna. Ejecutar
`python manage.py migrate` para aplicar el cambio en la base de datos.

Django guarda contraseñas con Argon2, valida formularios y protege CSRF. Las sesiones
se guardan en base de datos, duran dos horas desde su creación/modificación y usan
cookies HttpOnly y SameSite=Lax. Cerrar el navegador solicita finalizar la sesión,
aunque la restauración de sesiones del navegador puede conservarla. Con DEBUG=False
las cookies requieren HTTPS. Suspensión e inactividad bloquean login y recuperación
del usuario desde sesiones previas. El restablecimiento no inicia sesión ni reactiva
cuentas suspendidas. Las plantillas usan el escape HTML de Django.

## Correo de recuperación

Por defecto el mensaje se imprime en consola. Para correo real, configurar en `.env`:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=HOST_DEL_PROVEEDOR
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=USUARIO_SMTP
EMAIL_HOST_PASSWORD=CREDENCIAL_SMTP
DEFAULT_FROM_EMAIL=Agora Ticket <CORREO_AUTORIZADO>
```

Usar los datos del proveedor y reiniciar el servidor. No subir .env ni compartir
claves. El enlace usa el dominio de la solicitud: 127.0.0.1 funciona solo en esa
computadora; otros usuarios necesitan la URL pública con HTTPS y ALLOWED_HOSTS
restrictivo. La pantalla de solicitud recibida no garantiza entrega: revisar logs
si el correo no llega. El usuario confirmó que el envío real ya funciona.

## Pendientes y pruebas

La plantilla `templates/403.html` se muestra automáticamente cuando una vista
lanza `PermissionDenied`, como hace `role_required` ante un rol no autorizado.
Conserva la respuesta HTTP 403 y ofrece volver al panel o iniciar sesión.

Pendientes: integración de permisos con otros módulos,
acuerdo con Persona 5 y revisión final de seguridad (incluido límite de intentos).
Las pruebas anteriores se conservan; no se ejecutaron durante esta refactorización.
Para el cierre, se pueden ejecutar sin tocar PostgreSQL:

```powershell
python manage.py test users --settings=config.test_settings
```
