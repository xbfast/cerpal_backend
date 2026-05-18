# Ver logs del backend en producción (sin Docker)

La API escribe líneas con estos prefijos:

| Prefijo | Qué es |
|---------|--------|
| `[CERPAL_PASSWORD_RESET]` | Solicitud de recuperar contraseña |
| `[CERPAL_MAIL]` | Conexión y envío SMTP |

En el `.env` del servidor define:

```env
LOG_LEVEL=INFO
```

Tras cambiar variables `MAIL_*`, **reinicia siempre el proceso** que ejecuta uvicorn/gunicorn.

---

## 1. Comprobar SMTP sin leer logs

Desde cualquier máquina con `curl`:

```bash
curl -s https://api.cerpal.es/health/mail
```

Respuesta esperada si el correo está bien cargado:

```json
{
  "status": "ok",
  "configured": true,
  "mail_server": "smtp.office365.com",
  "mail_port": 587,
  "mail_from": "no_reply@cerpal.es",
  ...
}
```

Si `"configured": false`, la API arrancó sin SMTP válido (`.env` vacío, mal ubicado o sin reinicio).

---

## 2. Dónde están los logs (elige tu caso)

### A) Servicio systemd (lo más habitual en un VPS)

```bash
# Nombre del servicio: puede ser cerpal, cerpal-api, uvicorn, etc.
sudo systemctl list-units --type=service | grep -i cerpal

# Ver logs en vivo
sudo journalctl -u NOMBRE_DEL_SERVICIO -f

# Solo recuperación de contraseña
sudo journalctl -u NOMBRE_DEL_SERVICIO -f | grep CERPAL_PASSWORD_RESET

# Solo correo SMTP
sudo journalctl -u NOMBRE_DEL_SERVICIO -f | grep CERPAL_MAIL

# Últimas 200 líneas
sudo journalctl -u NOMBRE_DEL_SERVICIO -n 200 --no-pager
```

### B) PM2

```bash
pm2 list
pm2 logs NOMBRE_APP --lines 200
# o en vivo filtrando:
pm2 logs NOMBRE_APP | grep CERPAL_PASSWORD
```

### C) Supervisor

```bash
sudo supervisorctl status
sudo tail -f /var/log/supervisor/NOMBRE_PROGRAMA*.log
```

### D) Uvicorn en screen/tmux o con nohup

Si alguien arrancó a mano:

```bash
# Buscar el proceso
ps aux | grep uvicorn

# Si redirigió salida a un fichero, por ejemplo:
tail -f /ruta/al/log/uvicorn.log
# o
tail -f nohup.out
```

### E) Nginx

Nginx **no** guarda los logs de la aplicación Python; solo accesos HTTP. Para errores de la API usa journalctl/PM2, no `/var/log/nginx/`.

---

## 3. Probar recuperación y leer el resultado

1. En una terminal del servidor: `journalctl -u TU_SERVICIO -f | grep CERPAL`
2. En el navegador: https://cerpal.es/recuperar-contrasena con un email **que exista** en la base de datos (el mismo con el que haces login).
3. En el log deberías ver una secuencia como:

```
[CERPAL_PASSWORD_RESET] Petición POST /forgot-password | email solicitado=...
[CERPAL_PASSWORD_RESET] Cuenta encontrada (id=...). Enviando correo a ...
[CERPAL_MAIL] Conectando smtp.office365.com:587 ...
[CERPAL_MAIL] Enviado OK | asunto='Restablecer contraseña — CERPAL' ...
[CERPAL_PASSWORD_RESET] OK — correo enviado a ...
```

### Mensajes que indican el problema

| Log | Significado |
|-----|-------------|
| `No existe cuenta con ese email` | El email no está registrado; la web igual dice «Revisa tu correo» |
| `SMTP no configurado en este proceso` | Reinicia la API; revisa `/health/mail` |
| `Fallo SMTP` + traceback | Credenciales, puerto, o SMTP AUTH desactivado en Microsoft 365 |
| No aparece ninguna línea `CERPAL_PASSWORD_RESET` | La petición no llega a **esta** API (otro servidor, proxy, URL incorrecta) |

---

## 4. Script de prueba en el servidor (opcional)

En la carpeta del backend, con el mismo `.env` que usa la API:

```bash
cd /ruta/cerpal_backend
source venv/bin/activate   # si usáis venv
python3 -m app.send_test_mail tu@email.com
```

Si el script envía pero `/forgot-password` no, el problema no es Office 365 sino la API en ejecución (código viejo, otro `.env`, o email inexistente).
