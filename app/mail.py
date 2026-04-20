"""
SMTP con fastapi-mail. Los valores NO van en este archivo: van en variables de entorno.

En local, créalas en `cerpal_backend/.env` (copia de `.env.example`). Ese archivo se carga
al arrancar vía `python-dotenv` desde `app/database.py`.

En Docker/producción, define las mismas variables en el servicio (compose, Kubernetes, etc.);
no subas `.env` con secretos al repositorio.

Si `MAIL_SERVER` está vacío, el correo queda desactivado y la API funciona igual.

Variables:
  MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, MAIL_FROM_NAME,
  MAIL_STARTTLS, MAIL_SSL_TLS, MAIL_USE_CREDENTIALS, MAIL_VALIDATE_CERTS,
  MAIL_EHLO_HOSTNAME (opcional; ver docstring de _resolve_ehlo_hostname)
"""

from __future__ import annotations

import logging
import os

import aiosmtplib
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema
from fastapi_mail.fastmail import email_dispatched
from fastapi_mail.msg import MailMsg

logger = logging.getLogger(__name__)

_fast_mail: FastMail | None = None
_mail_config: ConnectionConfig | None = None


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _resolve_ehlo_hostname(mail_from: str) -> str | None:
    """
    Hostname en EHLO/HELO (local_hostname de aiosmtplib).

    - Si existe la variable de entorno MAIL_EHLO_HOSTNAME: su valor (vacío = dejar
      que la librería use el FQDN del sistema, p. ej. nombre del contenedor).
    - Si no está definida: `mail.<dominio>` a partir de MAIL_FROM, para evitar
      EHLO genérico en Docker que a veces se asocia peor a entrega/spam.

    Mailjet acepta el mensaje con 250 aunque luego el buzón filtre; un EHLO
    coherente con el dominio del remitente suele alinearse mejor con otras apps.
    """
    if "MAIL_EHLO_HOSTNAME" in os.environ:
        v = os.environ["MAIL_EHLO_HOSTNAME"].strip()
        return v or None
    if "@" not in mail_from:
        return None
    domain = mail_from.split("@", 1)[1].strip().lower()
    if not domain or "." not in domain:
        return None
    return f"mail.{domain}"


def _format_sender(conf: ConnectionConfig) -> str:
    if conf.MAIL_FROM_NAME:
        return f"{conf.MAIL_FROM_NAME} <{conf.MAIL_FROM}>"
    return str(conf.MAIL_FROM)


async def _build_mime_message(
    conf: ConnectionConfig, message: MessageSchema
):
    return await MailMsg(message)._message(_format_sender(conf))


async def _send_smtp(conf: ConnectionConfig, mime_msg, local_hostname: str | None) -> None:
    smtp = aiosmtplib.SMTP(
        hostname=conf.MAIL_SERVER,
        port=conf.MAIL_PORT,
        use_tls=conf.MAIL_SSL_TLS,
        start_tls=conf.MAIL_STARTTLS,
        validate_certs=conf.VALIDATE_CERTS,
        timeout=float(conf.TIMEOUT),
        local_hostname=local_hostname,
    )
    await smtp.connect()
    try:
        if conf.USE_CREDENTIALS:
            await smtp.login(conf.MAIL_USERNAME, conf.MAIL_PASSWORD)
        await smtp.send_message(mime_msg)
    finally:
        await smtp.quit()


def build_connection_config() -> ConnectionConfig | None:
    """Devuelve configuración SMTP o `None` si el correo no está activo."""
    server = os.getenv("MAIL_SERVER", "").strip()
    if not server:
        return None

    username = os.getenv("MAIL_USERNAME", "").strip()
    mail_from = os.getenv("MAIL_FROM", username).strip()
    if not mail_from:
        logger.warning(
            "MAIL_SERVER está definido pero faltan MAIL_FROM y MAIL_USERNAME; "
            "correo desactivado."
        )
        return None

    password = os.getenv("MAIL_PASSWORD", "")
    port_str = os.getenv("MAIL_PORT", "587").strip()
    try:
        port = int(port_str)
    except ValueError:
        logger.warning("MAIL_PORT inválido (%r); usando 587.", port_str)
        port = 587

    mail_ssl_tls = _env_bool("MAIL_SSL_TLS", "false")
    # aiosmtplib: STARTTLS (587) e SSL implícito (465) son incompatibles entre sí.
    mail_starttls = (
        False if mail_ssl_tls else _env_bool("MAIL_STARTTLS", "true")
    )

    from_name = os.getenv("MAIL_FROM_NAME", "").strip() or None

    try:
        return ConnectionConfig(
            MAIL_USERNAME=username,
            MAIL_PASSWORD=password,
            MAIL_FROM=mail_from,
            MAIL_FROM_NAME=from_name,
            MAIL_PORT=port,
            MAIL_SERVER=server,
            MAIL_STARTTLS=mail_starttls,
            MAIL_SSL_TLS=mail_ssl_tls,
            USE_CREDENTIALS=_env_bool("MAIL_USE_CREDENTIALS", "true"),
            VALIDATE_CERTS=_env_bool("MAIL_VALIDATE_CERTS", "true"),
        )
    except Exception:
        logger.exception("No se pudo crear la configuración SMTP.")
        return None


def init_mail() -> None:
    """Construye `FastMail` al arrancar la aplicación."""
    global _fast_mail, _mail_config

    conf = build_connection_config()
    if conf is None:
        _fast_mail = None
        _mail_config = None
        logger.info(
            "Correo SMTP desactivado: MAIL_SERVER no llega a este proceso. "
            "Docker: el contenedor no lee tu .env salvo que compose use `env_file: .env`. "
            "Local: revisa `cerpal_backend/.env`."
        )
        return

    _mail_config = conf
    _fast_mail = FastMail(conf)
    ehlo = _resolve_ehlo_hostname(str(conf.MAIL_FROM))
    logger.info(
        "Correo SMTP listo (servidor=%s, puerto=%s, EHLO=%s).",
        conf.MAIL_SERVER,
        conf.MAIL_PORT,
        ehlo or "(predeterminado del sistema)",
    )


def get_fast_mail() -> FastMail | None:
    """Instancia `FastMail` o `None` si no hay configuración."""
    return _fast_mail


def is_mail_configured() -> bool:
    return _fast_mail is not None


async def send_mail_message(message: MessageSchema) -> bool:
    """Envía un correo. Devuelve False si SMTP no está configurado."""
    conf = _mail_config
    if conf is None:
        logger.warning("Envío de correo omitido: SMTP no configurado.")
        return False
    if conf.SUPPRESS_SEND:
        mime_msg = await _build_mime_message(conf, message)
        email_dispatched.send(mime_msg)
        return True
    try:
        mime_msg = await _build_mime_message(conf, message)
        ehlo = _resolve_ehlo_hostname(str(conf.MAIL_FROM))
        await _send_smtp(conf, mime_msg, ehlo)
        email_dispatched.send(mime_msg)
        logger.info(
            "Correo enviado (asunto=%r, destinatarios=%s).",
            message.subject,
            message.recipients,
        )
        return True
    except Exception:
        logger.exception(
            "Fallo SMTP al enviar correo (asunto=%r, destinatarios=%s).",
            message.subject,
            message.recipients,
        )
        return False
