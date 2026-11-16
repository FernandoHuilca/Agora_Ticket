# Ágora Ticket - Gestión y Venta de Entradas Culturales

Aplicación web monolítica para la administración de eventos culturales, venta de tickets con validación QR y comunicación en tiempo real mediante WebSockets.

- **Aplicación en Producción (Render):** https://agora-ticket.onrender.com

## Stack Tecnológico

La explicación del módulo de cuentas está en [users/README.md](users/README.md).

- **Backend y Renderizado:** Python 3.12 + Django
- **Tiempo Real (WebSockets):** Django Channels + Daphne (ASGI)
- **Base de Datos:** PostgreSQL (Neon Cloud)
- **Almacenamiento Multimedia y Estáticos:** Cloudinary (imágenes y códigos QR) + WhiteNoise
- **CI/CD y Despliegue:** GitHub Actions + Render
- **Seguridad:** Hash de contraseñas con Argon2, protección CSRF y control de acceso por roles

---

## Instrucciones de Ejecución Local

Sigue estos pasos en orden para configurar el proyecto en tu computadora:

### Paso 1: Clonar el repositorio y ubicarse en la rama de desarrollo
Abre tu terminal en la carpeta donde quieras guardar el proyecto y ejecuta:

```powershell
git clone https://github.com/FernandoHuilca/Agora_Ticket.git
cd Agora_Ticket
git checkout develop
```

### Paso 2: Crear y activar el entorno virtual
Copia y pega este bloque completo en tu terminal de PowerShell:

```powershell
python -m venv venv
Set-ExecutionPolicy Unrestricted -Scope Process
.\venv\Scripts\activate
```
*(Si el comando `python` te abre la Microsoft Store o da error, usa `py -m venv venv` en la primera línea).*

### Paso 3: Instalar las dependencias
Con el entorno virtual activo `(venv)`, instala todas las librerías del proyecto:

```powershell
pip install -r requirements.txt
```

### Paso 4: Configurar las variables de entorno (`.env`)
1. En la raíz del proyecto (al mismo nivel que `manage.py`), haz una copia del archivo `.env.example` y renómbrala a **`.env`** (o crea el archivo `.env` desde cero).
2. Solicita al administrador del equipo las credenciales reales de la base de datos en la nube (Neon) y Cloudinary por interno y reemplaza los valores siguiendo esta estructura:

```env
SECRET_KEY=clave-secreta-desarrollo
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

DB_NAME=agora_ticket_db
DB_USER=tu_usuario_real_de_neon
DB_PASSWORD=tu_password_real_de_neon
DB_HOST=tu_host_real_de_neon.aws.neon.tech
DB_PORT=5432
DB_SSLMODE=require

CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
CLOUDINARY_CLOUD_NAME=tu_cloud_name
CLOUDINARY_API_KEY=tu_api_key
CLOUDINARY_API_SECRET=tu_api_secret

STRIPE_WEBHOOK_SECRET=tu_stripe_webhook_secret
```

### Paso 5: Ejecutar las migraciones y levantar el servidor
Una vez guardado tu archivo `.env` con las credenciales reales, ejecuta esto para sincronizar con la base de datos en la nube e iniciar el proyecto:

```powershell
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

Accede en tu navegador a: `http://127.0.0.1:8000`

---

## Chat en tiempo real (WebSockets)

Chat entre los compradores de un evento y su organizador (privado 1 a 1 y sala general
por evento), con historial en base de datos, usuarios conectados y contador de mensajes
no leídos en tiempo real. Implementado con Django Channels dentro del monolito.

- Funcionamiento, esquema de datos, protocolo y seguridad: [chat/README.md](chat/README.md)
- Puesta en marcha y despliegue en Render: [chat/DESPLIEGUE.md](chat/DESPLIEGUE.md)

`python manage.py runserver` ya atiende WebSockets (usa Daphne). En producción el
comando de inicio es `daphne -b 0.0.0.0 -p $PORT config.asgi:application`.

Pruebas automatizadas de todo el proyecto:

```powershell
python manage.py test --settings=config.test_settings
```

---

## Panel Administrativo, CI/CD y Despliegue en Producción

### 1. Panel de Administración (`/dashboard/`)
- **Métricas en tiempo real:** Conteo de usuarios activos/bloqueados, administradores, eventos publicados vigentes y boletos vendidos.
- **Moderación y reportes:** Activación o bloqueo de cuentas de usuario con prevención de auto-bloqueo y exportación de reportes en formato CSV.
- **Control de acceso:** Protegido mediante `@admin_required` (`custom_admin/views.py`), redirigiendo usuarios no autenticados a `/login/?next=/dashboard/` y usuarios sin rol administrativo a `/events/`.

### 2. Integración Continua (GitHub Actions)
El flujo `.github/workflows/ci.yml` se ejecuta automáticamente en cada `push` y `Pull Request` validando el estado del proyecto y los permisos de seguridad:

```powershell
python manage.py check
python manage.py test custom_admin
```

### 3. Despliegue en Render
- **URL pública:** `https://agora-ticket.onrender.com`
- **Build Command:** `pip install -r requirements.txt && python manage.py collectstatic --no-input && python manage.py migrate`
- **Start Command:** `daphne -b 0.0.0.0 -p $PORT config.asgi:application`

---

## Reglas de Ramas y Git Flow

- **`main`:** Rama protegida con código estable listo para despliegue.
- **`develop`:** Rama de integración de todos los módulos.

### Ramas por integrante (`feature/`):
Antes de empezar a programar tu módulo, asegúrate de estar en tu rama correspondiente (creándola desde `develop` con `git checkout -b nombre-de-tu-rama` o cambiándote a ella si ya existe):

- **Persona 1 (Auth y Seguridad):** `feature/registro`
- **Persona 2 (Eventos CRUD):** `feature/eventos-crud`
- **Persona 3 (Tickets y QR):** `feature/tickets-qr`
- **Persona 4 (Chat WebSocket):** `feature/chat-websocket`
- **Persona 5 (Admin y DevOps):** `feature/admin-dashboard`

> **Importante:** Todo cambio se integra hacia `develop` mediante un **Pull Request**. Queda estrictamente prohibido subir archivos `.env` o la carpeta `venv/` al repositorio.

---

## Pruebas con HTTPS y Stripe

### Servidor HTTPS (para la cámara del escáner)

```powershell
python manage.py runserver_plus --cert-file cert.crt --key-file cert.key 0.0.0.0:8000
```

Abrir en el celular: `https://<IP-de-tu-PC>:8000/tickets/escanear/` (aceptar la advertencia del certificado autofirmado).

Variables en `.env`:

```
SITE_URL=https://<IP-de-tu-PC>:8000
CSRF_TRUSTED_ORIGINS=https://<IP-de-tu-PC>:8000
```

Agregar `<IP-de-tu-PC>` a `ALLOWED_HOSTS`. Reiniciar el servidor tras cambiar el `.env`.

### Listener de Stripe (otra terminal)


```powershell
npm install -g @stripe/cli@latest

$env:STRIPE_API_KEY = "sk_test_XXXX"; stripe listen --all-snapshot --forward-to https://localhost:8000/tickets/webhooks/stripe/ --skip-verify
```

- `--skip-verify` es necesario porque el servidor local usa certificado autofirmado.
- Copiar el `whsec_...` que imprime a `STRIPE_WEBHOOK_SECRET` en `.env` y reiniciar el servidor.

### Tarjeta de prueba valida

`4242 4242 4242 4242`, cualquier fecha futura y cualquier CVC.


---

## Declaración de Uso de IA
Durante el desarrollo y configuración de este proyecto se utilizaron herramientas de Inteligencia Artificial como apoyo para la resolución de conflictos en Git y estandarización de la documentación técnica.