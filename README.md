# Ágora Ticket - Gestión y Venta de Entradas Culturales

Aplicación web monolítica para la administración de eventos culturales, venta de tickets con validación QR y comunicación en tiempo real mediante WebSockets.

## Stack Tecnológico
- **Backend y Renderizado:** Python 3.12 + Django
- **Tiempo Real (WebSockets):** Django Channels + Daphne (ASGI)
- **Base de Datos:** PostgreSQL (Neon Cloud)
- **Seguridad:** Hash de contraseñas con Argon2

---

## Instrucciones de Ejecución Local

Sigue estos pasos en orden para configurar el proyecto en tu computadora:

### Paso 1: Clonar el repositorio y ubicarse en la rama de desarrollo
Abre tu terminal en la carpeta donde quieras guardar el proyecto y ejecuta:

```powershell
git clone [https://github.com/FernandoHuilca/Agora_Ticket.git](https://github.com/FernandoHuilca/Agora_Ticket.git)
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
2. Solicita al administrador del equipo las credenciales reales de la base de datos en la nube (Neon) por interno y reemplaza los valores siguiendo esta estructura:

```env
SECRET_KEY=clave-secreta-desarrollo
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=agora_ticket_db
DB_USER=tu_usuario_real_de_neon
DB_PASSWORD=tu_password_real_de_neon
DB_HOST=tu_host_real_de_neon.aws.neon.tech
DB_PORT=5432
DB_SSLMODE=require
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

## Declaración de Uso de IA
Durante el desarrollo y configuración de este proyecto se utilizaron herramientas de Inteligencia Artificial como apoyo para la resolución de conflictos en Git y estandarización de la documentación técnica.