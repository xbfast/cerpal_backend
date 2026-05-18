"""Aviso interno cuando se registra una cuenta profesional."""

from __future__ import annotations

import logging
from typing import Any

from fastapi_mail import MessageSchema, MessageType

from app.email_template import email_info_box, esc, render_cerpal_email
from app.emails.notify_recipients import order_notify_recipients
from app.mail import is_mail_configured, send_mail_message

logger = logging.getLogger(__name__)


def _row(label: str, value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return ""
    return (
        f'<tr><td style="padding: 6px 0; color: #64748b; vertical-align: top;">'
        f"{esc(label)}</td>"
        f'<td style="padding: 6px 0; color: #0f172a;">{esc(text)}</td></tr>'
    )


def build_registration_notify_html(data: dict[str, Any]) -> str:
    rows = "".join(
        r
        for r in (
            _row("Empresa", data.get("nombre_empresa")),
            _row("CIF/NIF", data.get("cif_nif")),
            _row("Responsable", data.get("nombre_responsable")),
            _row("Email", data.get("email")),
            _row("Teléfono", data.get("telefono")),
            _row("Dirección", data.get("direccion")),
            _row("CP", data.get("cp")),
            _row("Ciudad", data.get("ciudad")),
            _row("Provincia", data.get("provincia")),
        )
        if r
    )
    body = f"""
      <p style="margin: 0 0 12px; font-size: 15px; color: #0f172a;">
        Se ha registrado una <strong>nueva cuenta profesional</strong> en CERPAL.
        Revisa y valida la cuenta en el panel de administración cuando corresponda.
      </p>
      {email_info_box(
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="font-size: 14px;">{rows}</table>'
      )}
    """
    return render_cerpal_email(
        title="Nuevo registro profesional",
        greeting="Equipo CERPAL",
        body_html=body,
    )


def registration_notify_payload_from_account(account: Any) -> dict[str, Any]:
    return {
        "nombre_empresa": account.nombre_empresa,
        "cif_nif": account.cif_nif,
        "nombre_responsable": account.nombre_responsable,
        "email": account.email,
        "telefono": account.telefono,
        "direccion": account.direccion,
        "cp": account.cp,
        "ciudad": account.ciudad,
        "provincia": account.provincia,
    }


async def send_registration_notify_email(data: dict[str, Any]) -> None:
    recipients = order_notify_recipients()
    if not recipients:
        logger.info(
            "Registro de %s: MAIL_ORDER_NOTIFY vacío; no se envía aviso interno.",
            data.get("email"),
        )
        return
    if not is_mail_configured():
        logger.warning(
            "Registro de %s pero correo no configurado; no se envía aviso a MAIL_ORDER_NOTIFY.",
            data.get("email"),
        )
        return

    subject = f"Nuevo registro — {data.get('nombre_empresa', 'Cuenta profesional')}"
    body = build_registration_notify_html(data)
    ok = await send_mail_message(
        MessageSchema(
            subject=subject,
            recipients=recipients,
            body=body,
            subtype=MessageType.html,
        )
    )
    if ok:
        logger.info(
            "Aviso de registro enviado a MAIL_ORDER_NOTIFY (%s) para %s.",
            recipients,
            data.get("email"),
        )
    else:
        logger.error(
            "No se pudo enviar aviso de registro a MAIL_ORDER_NOTIFY para %s.",
            data.get("email"),
        )
