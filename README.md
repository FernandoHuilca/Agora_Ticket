# Ágora Ticket - Gestión y Venta de Entradas Culturales

Aplicación web monolítica para la administración de eventos culturales, venta de tickets con validación QR y comunicación en tiempo real mediante WebSockets.

## Stack Tecnológico
- **Backend y Renderizado:** Python 3.12 + Django
- **Tiempo Real (WebSockets):** Django Channels + Daphne (ASGI)
- **Base de Datos:** PostgreSQL (Neon Cloud)
- **Seguridad:** Hash de contraseñas con Argon2

## Instrucciones de Ejecución Local

1. **Clonar el repositorio y ubicarse en la rama `develop`:**
   ```bash
   git clone https://github.com/FernandoHuilca/Agora_Ticket
   cd agora-ticket
   git checkout develop

Paso 1: Crear y activar el entorno virtual
Copia y pega este bloque completo en tu terminal de PowerShell:

python -m venv venv
Set-ExecutionPolicy Unrestricted -Scope Process
.\venv\Scripts\activate

Paso 2: Instalar las dependencias
Copia y pega este bloque en tu terminal:

pip install daphne channels channels-redis psycopg2-binary python-dotenv argon2-cffi pillow qrcode
pip freeze > requirements.txt

Paso 3: Ejecutar las migraciones y levantar el servidor
Una vez que ya hayas configurado tu archivo .env con los datos de Neon, copia y pega esto para probar la conexión con la base de datos:

python manage.py makemigrations
python manage.py migrate
python manage.py runserver

Accede en tu navegador a http://127.0.0.1:8000.

Reglas de Ramas y Git Flowmain: 
- main: Rama protegida con código estable listo para despliegue.   
- develop: Rama de integración de todos los módulos.   

Ramas por integrante (feature/):

- Persona 1 (Auth y Seguridad): feature/registro   
- Persona 2 (Eventos CRUD): feature/eventos-crud   
- Persona 3 (Tickets y QR): feature/tickets-qr   
- Persona 4 (Chat WebSocket): feature/chat-websocket   
- Persona 5 (Admin y DevOps): feature/admin-dashboard   

Todo cambio se integra hacia develop mediante un Pull Request. Prohibido subir archivos .env.

Declaración de Uso de IA