# Eventos y gestión de cartelera — primer bimestre

## Cómo está organizado

| Archivo | Para qué sirve |
| --- | --- |
| `models.py` | Entidad `Event`, índices de búsqueda, restricciones `CheckConstraint` y reglas de dominio. |
| `validators.py` | Validación de imágenes (tamaño, extensión, *magic bytes*) y sanitización EXIF/conversión a WEBP. |
| `forms.py` | Formularios de creación/edición (`EventForm`), filtros de cartelera (`EventFilterForm`) y moderación/baja (`EventModerationForm`). |
| `views.py` | Cartelera pública, detalle, panel del organizador (CRUD e inscritos), baja administrativa y emisión de avisos WebSocket. |
| `urls.py` | Rutas del módulo bajo el namespace `events`. |
| `tests.py` | 16 pruebas automatizadas (TDD) de modelo, validadores, filtros, paginación, seguridad RBAC/IDOR y procesamiento de imágenes. |
| `templates/events/` | Plantillas HTML renderizadas en servidor para cartelera y gestión de eventos. |

## Rutas y permisos del módulo (`/eventos/`)

| Ruta | Nombre (`url`) | Método(s) | Acceso / Rol requerido | Descripción |
| --- | --- | --- | --- | --- |
| `/eventos/` | `events:home` | `GET` | Público | Cartelera paginada (6 por página) de eventos `APPROVED` con búsqueda y filtros. |
| `/eventos/<uuid:pk>/` | `events:detail` | `GET` | Público (`APPROVED`) / Dueño o Admin (otros estados) | Detalle completo del evento, aforo disponible y condiciones de acceso. |
| `/eventos/mis-eventos/` | `events:org_list` | `GET` | `organizer`, `admin` | Panel paginado con los eventos propios del organizador (o todos para `admin`). |
| `/eventos/nuevo/` | `events:org_new` | `GET`, `POST` | `organizer`, `admin` | Creación y publicación directa de eventos (`APPROVED`) con notificación en tiempo real. |
| `/eventos/<uuid:pk>/editar/` | `events:edit` | `GET`, `POST` | `organizer` (dueño), `admin` | Actualización de datos del evento respetando el piso de entradas ya vendidas. |
| `/eventos/<uuid:pk>/eliminar/` | `events:delete` | `GET`, `POST` | `organizer` (dueño), `admin` | Eliminación con confirmación, bloqueada si existen entradas emitidas. |
| `/eventos/<uuid:pk>/inscritos/` | `events:attendees` | `GET` | `organizer` (dueño), `admin` | Consulta de asistentes registrados y balance de cupos disponibles. |
| `/eventos/moderacion/` | `events:moderation_list` | `GET` | `admin` | Bandeja administrativa para auditoría y revisión de eventos por estado. |
| `/eventos/<uuid:pk>/moderar/` | `events:moderate` | `GET`, `POST` | `admin` | Acción administrativa para dar de baja (`REJECTED`) o reactivar publicaciones con motivo obligatorio. |

## Reglas de negocio e integridad de datos

1. **Autonomía del organizador y publicación directa:** Dado que el rol `organizer` es asignado por administración, los eventos creados desde `org_new` se publican en estado `APPROVED` e inicializan `available_tickets = capacity`.
2. **Duración y coherencia temporal:**
   - Al crear un evento nuevo, `start_date` debe ser una fecha futura.
   - `end_date` debe ser posterior a `start_date`, con una duración mínima de **30 minutos** y máxima de **24 horas**.
3. **Modalidad gratuita vs. de pago:**
   - Si `is_free = True`, el precio se fuerza a `$0.00` y se habilita el límite `max_tickets_per_user` (por defecto 4).
   - Si `is_free = False`, el sistema exige un `price > 0.00`.
4. **Protección del aforo e integridad en edición/borrado:**
   - A nivel de base de datos (`CheckConstraint`), se exige `capacity > 0`, `price >= 0` y `available_tickets <= capacity`.
   - En la edición de un evento existente, no se permite reducir `capacity` por debajo del número de entradas ya emitidas (`capacity - available_tickets`). Si el aforo total cambia válidamente, `available_tickets` se recalcula de forma automática.
   - Un evento con entradas emitidas (`available_tickets < capacity`) no puede ser eliminado (`HTTP 400 Bad Request`).
5. **Rendimiento e indexación:** Se aplican índices simples sobre `name`, `category`, `start_date` y `status`, además de los índices compuestos `idx_event_status_start` y `idx_event_category_status` para optimizar las consultas de la cartelera.

## Controles de seguridad (Desarrollo de Software Seguro)

- **Prevención de IDOR y enumeración:** La clave primaria de `Event` es un `UUIDv4`. Todas las vistas de modificación (`edit`, `delete`) y consulta privada (`attendees`) verifican en el servidor que `event.organizer_id == request.user.id` (o que el usuario tenga rol `admin`); cualquier intento de manipular la URL desde otra cuenta de organizador lanza `PermissionDenied` (`403 Forbidden`).
- **Control de acceso por rol (RBAC):** Integrado con el decorador `@role_required` de `users.permissions`.
- **Seguridad en subida de imágenes (`validators.py`):**
  - Tamaño máximo restringido a **2 MB** (mitigación de DoS en almacenamiento/memoria).
  - Rechazo de archivos `.svg` y validación de *magic bytes* reales con Pillow (`JPEG`, `PNG`, `WEBP`) para prevenir **Stored XSS**.
  - Re-codificación en memoria (`sanitize_and_optimize_image`): toda imagen subida se redimensiona a un máximo de `1600x1600 px` y se re-escribe en formato `.webp`, eliminando metadatos EXIF (como ubicación GPS) y posibles cargas ocultas (*polyglot files*).

## Almacenamiento de imágenes (Cloudinary / Local)

La base de datos almacena únicamente la referencia/URL del archivo en el campo `image`.
- **Producción / Con credenciales en `.env`:** Usa `MediaCloudinaryStorage` enviando los afiches a Cloudinary bajo conexión HTTPS (`SECURE=True`).
- **Desarrollo sin credenciales y entorno de pruebas (`manage.py test`):** Conmuta automáticamente a `FileSystemStorage` local para no requerir red ni consumir cuota durante las pruebas automatizadas.

Variables requeridas en `.env` para habilitar Cloudinary:

```dotenv
CLOUDINARY_URL=cloudinary://API_KEY:API_SECRET@CLOUD_NAME
CLOUDINARY_CLOUD_NAME=tu_cloud_name
CLOUDINARY_API_KEY=tu_api_key
CLOUDINARY_API_SECRET=tu_api_secret