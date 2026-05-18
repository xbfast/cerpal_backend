"""
Correo transaccional por SMTP (IONOS u otro proveedor).

Variables en `cerpal_backend/.env` (ver `.env.example`).
Sin `MAIL_SERVER` el correo queda desactivado y la API sigue funcionando.
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


def _secret_value(value: object) -> str:
    """fastapi-mail guarda MAIL_PASSWORD como SecretStr; aiosmtplib exige str."""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(value) if value is not None else ""


def _resolve_ehlo_hostname(mail_from: str) -> str | None:
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
            await smtp.login(
                _secret_value(conf.MAIL_USERNAME),
                _secret_value(conf.MAIL_PASSWORD),
            )
        await smtp.send_message(mime_msg)
    finally:
        await smtp.quit()


def build_connection_config() -> ConnectionConfig | None:
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
    mail_starttls = (
        False if mail_ssl_tls else _env_bool("MAIL_STARTTLS", "true")
    )
    from_name = os.getenv("MAIL_FROM_NAME", "").strip() or None

    try:
        timeout = float(os.getenv("MAIL_TIMEOUT", "30").strip())
    except ValueError:
        timeout = 30.0
    timeout = max(5.0, min(timeout, 120.0))

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
            TIMEOUT=timeout,
        )
    except Exception:
        logger.exception("No se pudo crear la configuración SMTP.")
        return None


def init_mail() -> None:
    global _fast_mail, _mail_config

    conf = build_connection_config()
    if conf is None:
        _fast_mail = None
        _mail_config = None
        logger.warning(
            "Correo SMTP desactivado: MAIL_SERVER vacío. "
            "Revisa `cerpal_backend/.env` en el servidor."
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
    return _fast_mail


def is_mail_configured() -> bool:
    return _fast_mail is not None


async def send_mail_message(message: MessageSchema) -> bool:
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
        logger.info(
            "Conectando a SMTP %s:%s (timeout %ss)…",
            conf.MAIL_SERVER,
            conf.MAIL_PORT,
            conf.TIMEOUT,
        )
        await _send_smtp(conf, mime_msg, ehlo)
        email_dispatched.send(mime_msg)
        logger.info(
            "Correo enviado (asunto=%r, destinatarios=%s).",
            message.subject,
            message.recipients,
        )
        return True
    except Exception as e:
        logger.exception(
            "Fallo SMTP al enviar correo (asunto=%r, destinatarios=%s, servidor=%s:%s): %s",
            message.subject,
            message.recipients,
            conf.MAIL_SERVER,
            conf.MAIL_PORT,
            e,
        )
        return False
