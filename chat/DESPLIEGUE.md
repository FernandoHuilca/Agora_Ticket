# Chat — lo que te toca hacer a ti

El código está completo y probado en local. Estos son los pasos manuales, en orden.
Cómo funciona el chat por dentro: [README.md](README.md).

## 1. Probarlo en tu máquina

```powershell
.\venv\Scripts\activate
pip install -r requirements.txt      # no hay dependencias nuevas; por si acaso
python manage.py migrate             # crea las 4 tablas del chat (chat.0001_initial)
python manage.py runserver
```

> **Ojo:** tu `.env` apunta a la base compartida de Neon. `migrate` crea las tablas
> del chat ahí para todo el equipo. Es seguro (solo agrega tablas nuevas), pero avisa
> al grupo. Solo hay que hacerlo una vez.

`runserver` ya sirve WebSockets porque `daphne` está en `INSTALLED_APPS`.

Para ver el chat funcionando necesitas **dos sesiones a la vez** (por ejemplo, una
ventana normal y una de incógnito):

1. Sesión A: un **organizador** con un evento publicado.
2. Sesión B: un **cliente** que obtenga una entrada de ese evento (con un evento
   gratuito el ticket se emite al instante, sin pasar por Stripe).
3. En B: **Mis tickets → abrir el ticket → «Chatear con el organizador»** y envía un mensaje.
4. En A: aparece el **contador en «Mensajes»** y un aviso emergente, sin recargar.
   Entra a «Mensajes», abre la conversación y responde.

### Si pruebas con HTTPS local (cámara del escáner)

`runserver_plus` (el comando del README para HTTPS) **no soporta WebSockets**: es un
servidor WSGI. Para probar el chat con HTTPS usa Daphne con los mismos certificados:

```powershell
python manage.py collectstatic --no-input
daphne -e ssl:8000:privateKey=cert.key:certKey=cert.crt:interface=0.0.0.0 config.asgi:application
```

## 2. Subir los cambios

No hice ningún commit. Estás en la rama `feature/chat-websocket`:

```powershell
git add -A
git commit -m "Agrega chat en tiempo real con Django Channels"
git push -u origin feature/chat-websocket
```

Después abre el **Pull Request hacia `develop`** en GitHub.

## 3. Render

### 3.1 Start Command (lo más importante)

En Render → tu Web Service → **Settings → Start Command** debe ser:

```bash
daphne -b 0.0.0.0 -p $PORT config.asgi:application
```

Si hoy dice `gunicorn config.wsgi` (o similar), **cámbialo**: Gunicorn/WSGI no
atiende WebSockets y el chat se quedaría en «Reconectando…».

### 3.2 Build Command

Déjalo como está (`./build.sh`). Ya ejecuta `migrate`, así que las tablas del chat
se crean en el despliegue.

### 3.3 Variables de entorno

No hay variables nuevas obligatorias. Revisa que estas (que ya deberían existir)
incluyan tu dominio, porque ahora también protegen el WebSocket:

| Variable | Valor | Por qué importa para el chat |
| --- | --- | --- |
| `ALLOWED_HOSTS` | `agora-ticket.onrender.com` (tu dominio, sin `https://`) | El servidor rechaza handshakes WebSocket cuyo `Origin` no esté aquí. |
| `CSRF_TRUSTED_ORIGINS` | `https://agora-ticket.onrender.com` | Ya se usaba para los formularios. |
| `DEBUG` | `False` | Cookies de sesión solo por HTTPS. |

**`wss://` no requiere configuración**: Render sirve el sitio por HTTPS y el
navegador abre el WebSocket como `wss://` automáticamente.

### 3.4 Redis (opcional — solo si escalas)

Con **una sola instancia** (plan gratuito) no hace falta nada: se usa la capa en
memoria. Solo si algún día configuras más de una instancia o más de un proceso:

1. Render → **New → Key Value** (el plan gratuito alcanza), misma región que la app.
2. Copia su **Internal URL** (`redis://red-xxxx:6379`).
3. En el Web Service agrega la variable `REDIS_URL` con ese valor y vuelve a desplegar.

El código lo detecta solo (`config/settings.py`); `channels_redis` ya está en
`requirements.txt`.

### 3.5 Comprobar en producción

1. Abre el sitio con dos cuentas (organizador y comprador) y repite la prueba del paso 1.
2. En el navegador: **F12 → Red → WS**. Deben aparecer dos conexiones con estado
   `101`: `/ws/notificaciones/` y `/ws/chat/<id>/`, con URL `wss://…`. Esa captura
   sirve como evidencia de «conexión segura (wss) en el despliegue».

### 3.6 Si algo falla

| Síntoma | Causa probable |
| --- | --- |
| El chat se queda en «Reconectando…» y en la pestaña WS se ve `403` | `ALLOWED_HOSTS` no incluye el dominio, o la sesión caducó (vuelve a iniciar sesión). |
| En la pestaña WS se ve `404` o la conexión nunca abre | El Start Command no es Daphne. |
| Los mensajes llegan a unos usuarios y a otros no | Hay más de una instancia/proceso sin `REDIS_URL`. |
| Tras un rato inactivo tarda en conectar | El plan gratuito de Render duerme el servicio; el chat se reconecta solo al despertar. |

## 4. Pendientes de la guía que dependen de ti

- **README raíz**: ya agregué la sección del chat. Falta que declares el uso de IA
  en este módulo (la guía lo exige en la sección «Uso de IA»): el chat se generó con
  Claude Code y debes poder explicarlo; la sección 7 de [README.md](README.md) resume
  lo que suelen preguntar en la defensa (handshake, eventos, mecanismos de respaldo).
- **Diagrama de arquitectura** de la presentación: puedes usar los diagramas Mermaid
  de [README.md](README.md) (GitHub los dibuja).
- **CI**: `.github/workflows/ci.yml` solo ejecuta `manage.py check`. Si quieren que
  también corra las pruebas, agreguen el paso
  `python manage.py test --settings=config.test_settings`.
- **Etiqueta de entrega** `v1.0-b1` cuando todo esté en `main`.
