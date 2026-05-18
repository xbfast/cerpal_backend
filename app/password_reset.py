"""Generación de tokens de recuperación, URL del frontend y envío por SMTP."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi_mail import MessageSchema, MessageType

from app.email_template import (
    email_button,
    email_muted_paragraph,
    esc,
    public_frontend_base,
    render_cerpal_email,
)
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


def build_password_reset_url(plain_token: str) -> str:
    qs = urlencode({"token": plain_token})
    return f"{public_frontend_base()}/recuperar-contrasena/nueva?{qs}"


def password_reset_email_html(recipient_name: str, reset_url: str) -> str:
    name = (recipient_name or "").strip() or "Hola"
    body = f"""
      <p style="margin: 0 0 12px; font-size: 15px; color: #0f172a;">
        Has solicitado restablecer la contraseña de tu cuenta profesional en <strong>CERPAL</strong>.
      </p>
      <p style="margin: 0; font-size: 15px; color: #0f172a;">
        Pulsa el botón para elegir una contraseña nueva (el enlace caduca en unas horas):
      </p>
      {email_button(reset_url, "Restablecer contraseña")}
      <p style="margin: 0; font-size: 14px; color: #4A5565;">Si el botón no funciona, copia esta dirección:</p>
      <p style="margin: 8px 0 0; font-size: 13px; word-break: break-all; color: #314158;">{esc(reset_url)}</p>
      {email_muted_paragraph("Si no has sido tú, ignora este mensaje; tu contraseña no cambiará.")}
    """
    return render_cerpal_email(
        title="Restablecer contraseña",
        greeting=name,
        body_html=body,
    )


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
    if ok:
        logger.info("Correo de recuperación enviado a %s.", to_email)
    else:
        logger.error("No se pudo enviar el correo de recuperación a %s.", to_email)
