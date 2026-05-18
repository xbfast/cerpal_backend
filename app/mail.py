"""
Correo transaccional: Brevo (API HTTPS) o SMTP (IONOS, Office 365, etc.).

En VPS con SMTP bloqueado (p. ej. DigitalOcean), usa Brevo:
  BREVO_API_KEY=...
  MAIL_FROM=correo_verificado_en_brevo@tudominio.com
  MAIL_FROM_NAME=CERPAL
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from typing import Literal

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema
from fastapi_mail.fastmail import email_dispatched
from fastapi_mail.msg import MailMsg

from app.mail_brevo import BrevoConfig, build_brevo_config, send_brevo_message

logger = logging.getLogger(__name__)

MailProvider = Literal["brevo", "smtp"]

_fast_mail: FastMail | None = None
_mail_config: ConnectionConfig | None = None
_brevo_config: BrevoConfig | None = None
_mail_provider: MailProvider | None = None


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _secret_value(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(value) if value is not None else ""


def _resolve_mail_provider() -> MailProvider | None:
    explicit = os.getenv("MAIL_PROVIDER", "").strip().lower()
    has_brevo = bool(os.getenv("BREVO_API_KEY", "").strip())
    has_smtp = bool(os.getenv("MAIL_SERVER", "").strip())

    if explicit == "brevo":
        return "brevo" if has_brevo else None
    if explicit == "smtp":
        return "smtp" if has_smtp else None
    if has_brevo:
        return "brevo"
    if has_smtp:
        return "smtp"
    return None


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


async def _build_mime_message(conf: ConnectionConfig, message: MessageSchema):
    return await MailMsg(message)._message(_format_sender(conf))


def _smtp_ssl_context(validate_certs: bool) -> ssl.SSLContext:
    if validate_certs:
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def _send_smtp_sync(
    conf: ConnectionConfig, mime_msg, local_hostname: str | None
) -> None:
    timeout = float(conf.TIMEOUT)
    host = conf.MAIL_SERVER
    port = int(conf.MAIL_PORT)
    username = _secret_value(conf.MAIL_USERNAME)
    password = _secret_value(conf.MAIL_PASSWORD)
    ssl_context = _smtp_ssl_context(conf.VALIDATE_CERTS)

    if conf.MAIL_SSL_TLS:
        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            local_hostname=local_hostname,
            context=ssl_context,
        ) as smtp:
            if conf.USE_CREDENTIALS:
                smtp.login(username, password)
            smtp.send_message(mime_msg)
        return

    with smtplib.SMTP(
        host,
        port,
        timeout=timeout,
        local_hostname=local_hostname,
    ) as smtp:
        if conf.MAIL_STARTTLS:
            smtp.starttls(context=ssl_context)
        if conf.USE_CREDENTIALS:
            smtp.login(username, password)
        smtp.send_message(mime_msg)


async def _send_smtp(
    conf: ConnectionConfig, mime_msg, local_hostname: str | None
) -> None:
    await asyncio.to_thread(_send_smtp_sync, conf, mime_msg, local_hostname)


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
    global _fast_mail, _mail_config, _brevo_config, _mail_provider

    _fast_mail = None
    _mail_config = None
    _brevo_config = None
    _mail_provider = _resolve_mail_provider()

    if _mail_provider is None:
        logger.warning(
            "Correo desactivado: define BREVO_API_KEY (recomendado en DigitalOcean) "
            "o MAIL_SERVER para SMTP."
        )
        return

    if _mail_provider == "brevo":
        _brevo_config = build_brevo_config()
        if _brevo_config is None:
            _mail_provider = None
            logger.warning("Brevo no configurado correctamente (BREVO_API_KEY / MAIL_FROM).")
            return
        logger.info(
            "Correo listo vía Brevo API (remitente=%s, nombre=%s).",
            _brevo_config.mail_from,
            _brevo_config.mail_from_name or "(sin nombre)",
        )
        return

    conf = build_connection_config()
    if conf is None:
        _mail_provider = None
        logger.warning("SMTP no configurado correctamente.")
        return

    _mail_config = conf
    _fast_mail = FastMail(conf)
    ehlo = _resolve_ehlo_hostname(str(conf.MAIL_FROM))
    logger.info(
        "Correo listo vía SMTP (servidor=%s, puerto=%s, EHLO=%s).",
        conf.MAIL_SERVER,
        conf.MAIL_PORT,
        ehlo or "(predeterminado del sistema)",
    )


def get_fast_mail() -> FastMail | None:
    return _fast_mail


def is_mail_configured() -> bool:
    return _mail_provider is not None


def get_mail_provider() -> MailProvider | None:
    return _mail_provider


async def send_mail_message(message: MessageSchema) -> bool:
    if _mail_provider is None:
        logger.warning("Envío de correo omitido: correo no configurado.")
        return False

    if _mail_provider == "brevo":
        assert _brevo_config is not None
        try:
            await send_brevo_message(
                _brevo_config,
                subject=message.subject,
                recipients=message.recipients,
                html_body=message.body,
            )
            logger.info(
                "Correo enviado (Brevo, asunto=%r, destinatarios=%s).",
                message.subject,
                message.recipients,
            )
            return True
        except Exception as e:
            logger.exception(
                "Fallo Brevo al enviar correo (asunto=%r, destinatarios=%s): %s",
                message.subject,
                message.recipients,
                e,
            )
            return False

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
            "Correo enviado (SMTP, asunto=%r, destinatarios=%s).",
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
