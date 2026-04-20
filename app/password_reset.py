"""Generación de tokens de recuperación, URL del frontend y envío por SMTP."""

from __future__ import annotations

import hashlib
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi_mail import MessageSchema, MessageType

from app.mail import is_mail_configured, send_mail_message

logger = logging.getLogger(__name__)


def hash_password_reset_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_password_reset_secret() -> tuple[str, str, datetime]:
    """
    Devuelve (token_plano_para_el_enlace, hash_para_BD, fecha_caducidad_UTC_naive).
    """
    plain = secrets.token_urlsafe(32)
    token_hash = hash_password_reset_token(plain)
    try:
        hours = int(os.getenv("PASSWORD_RESET_TOKEN_HOURS", "24").strip())
    except ValueError:
        hours = 24
    hours = max(1, min(hours, 168))
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours)
    return plain, token_hash, expires


def public_frontend_base() -> str:
    return os.getenv("PUBLIC_FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")


def build_password_reset_url(plain_token: str) -> str:
    qs = urlencode({"token": plain_token})
    return f"{public_frontend_base()}/recuperar-contrasena/nueva?{qs}"


def password_reset_email_html(recipient_name: str, reset_url: str) -> str:
    name = html.escape((recipient_name or "").strip() or "Hola")
    safe_url = html.escape(reset_url)
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8" /></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #0a0a0a;">
  <p>{name},</p>
  <p>Has solicitado restablecer la contraseña de tu cuenta profesional en <strong>CERPAL</strong>.</p>
  <p>Pulsa el botón para elegir una contraseña nueva (el enlace caduca en unas horas):</p>
  <p style="margin: 24px 0;">
    <a href="{safe_url}" style="display: inline-block; padding: 12px 24px; background: #121A2E; color: #fff; text-decoration: none; border-radius: 10px; font-weight: 600;">
      Restablecer contraseña
    </a>
  </p>
  <p style="font-size: 14px; color: #4A5565;">Si el botón no funciona, copia y pega esta dirección en el navegador:</p>
  <p style="font-size: 13px; word-break: break-all; color: #314158;">{safe_url}</p>
  <p style="font-size: 14px; color: #4A5565;">Si no has sido tú, ignora este mensaje; tu contraseña no cambiará.</p>
</body>
</html>"""


async def send_password_reset_email(
    to_email: str, recipient_display: str, plain_token: str
) -> None:
    if not is_mail_configured():
        logger.warning(
            "Recuperación solicitada para %s pero SMTP no está configurado; "
            "no se ha enviado el correo.",
            to_email,
        )
        return
    reset_url = build_password_reset_url(plain_token)
    body = password_reset_email_html(recipient_display, reset_url)
    ok = await send_mail_message(
        MessageSchema(
            subject="Restablecer contraseña — CERPAL",
            recipients=[to_email],
            body=body,
            subtype=MessageType.html,
        )
    )
    if not ok:
        logger.error("No se pudo enviar el correo de recuperación a %s.", to_email)
