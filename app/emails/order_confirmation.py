"""Correo de copia del pedido al confirmar checkout."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi_mail import MessageSchema, MessageType

from app.cart_schemas import CartLineItem
from app.email_template import (
    email_button,
    email_info_box,
    email_muted_paragraph,
    esc,
    public_frontend_base,
    render_cerpal_email,
)
from app.mail import is_mail_configured, send_mail_message
from app.order_enums import MetodoPago
from app.order_schemas import PedidoOut

logger = logging.getLogger(__name__)

_METODO_PAGO_LABEL = {
    MetodoPago.TRANSFER: "Transferencia bancaria",
    MetodoPago.CARD: "Tarjeta",
}

_TIPO_ENVIO_LABEL = {
    "delivery": "Envío a domicilio",
    "warehouse": "Recogida en almacén",
}


def _format_eur(value: Decimal | float) -> str:
    x = float(value)
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _format_datetime(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y %H:%M")


def _line_selections(line: CartLineItem) -> list[tuple[str, str]]:
    if line.kind == "m2":
        raw = line.rotulacion_selections
    elif line.catalog == "impresion":
        raw = line.impresion_selections
    elif line.catalog == "rotulacion":
        raw = line.rotulacion_selections
    else:
        raw = None
    out: list[tuple[str, str]] = []
    if raw:
        for item in raw:
            label = (item.label or "").strip()
            value = (item.value or "").strip()
            if label and value:
                out.append((label, value))
    return out


def _line_extra_text(line: CartLineItem) -> str | None:
    parts: list[str] = []
    if line.unit_label and line.catalog != "impresion" and line.kind != "m2":
        parts.append(line.unit_label.strip())
    if line.options_summary and not _line_selections(line):
        parts.append(line.options_summary.strip())
    if line.kind == "m2" and line.surface_m2 is not None:
        parts.append(f"{line.surface_m2:.2f} m²".replace(".", ","))
    if line.detail_line:
        parts.append(line.detail_line.strip())
    if not parts:
        return None
    return " · ".join(parts)


def _line_row_html(line: CartLineItem) -> str:
    line_total = float(line.price_per_unit) * line.quantity
    selections = _line_selections(line)
    extra = _line_extra_text(line)
    sel_html = ""
    if selections:
        rows = "".join(
            f'<tr><td style="padding: 2px 8px 2px 0; color: #64748b; vertical-align: top; white-space: nowrap;">'
            f"{esc(label)}</td>"
            f'<td style="padding: 2px 0; color: #0f172a;">{esc(value)}</td></tr>'
            for label, value in selections
        )
        sel_html = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="margin: 8px 0 0; font-size: 12px;">{rows}</table>'
        )
    extra_html = (
        f'<p style="margin: 6px 0 0; font-size: 12px; color: #64748b;">{esc(extra)}</p>'
        if extra
        else ""
    )
    return f"""
    <tr>
      <td style="padding: 14px 0; border-bottom: 1px solid #e5e7eb;">
        <p style="margin: 0; font-size: 15px; font-weight: 600; color: #0f172a;">{esc(line.title)}</p>
        <p style="margin: 4px 0 0; font-size: 12px; color: #64748b;">Ref. {esc(line.product_ref)} · Cant. {line.quantity}</p>
        {sel_html}
        {extra_html}
      </td>
      <td style="padding: 14px 0; border-bottom: 1px solid #e5e7eb; text-align: right; vertical-align: top; white-space: nowrap; font-weight: 600;">
        {esc(_format_eur(line_total))}
      </td>
    </tr>"""


def _shipping_address_html(snapshot: dict) -> str:
    name = (snapshot.get("name") or "").strip()
    direccion = (snapshot.get("direccion") or "").strip()
    cp = (snapshot.get("cp") or "").strip()
    ciudad = (snapshot.get("ciudad") or "").strip()
    provincia = (snapshot.get("provincia") or "").strip()
    line2 = " ".join(p for p in [cp, ciudad, provincia] if p)
    parts = [p for p in [name, direccion, line2] if p]
    if not parts:
        return ""
    return "<br />".join(esc(p) for p in parts)


def _transfer_block_html(pedido: PedidoOut) -> str:
    iban = os.getenv("BANK_TRANSFER_IBAN", "").strip()
    beneficiary = os.getenv("BANK_TRANSFER_BENEFICIARY", "").strip()
    bank_name = os.getenv("BANK_TRANSFER_BANK_NAME", "").strip()
    swift = os.getenv("BANK_TRANSFER_SWIFT", "").strip()
    ticket = pedido.ticket_number
    referencia = (pedido.referencia_pedido_cliente or "").strip()
    concept_parts = [ticket]
    if referencia:
        concept_parts.append(referencia)
    concept = " — ".join(concept_parts)

    lines = [
        '<p style="margin: 0 0 8px; font-size: 14px; font-weight: 600; color: #14532d;">'
        "Pago por transferencia bancaria</p>",
        f'<p style="margin: 0; font-size: 14px; color: #166534;">Indica en el concepto: '
        f"<strong>{esc(concept)}</strong></p>",
    ]
    if beneficiary:
        lines.append(
            f'<p style="margin: 8px 0 0; font-size: 13px; color: #166534;">Beneficiario: '
            f"<strong>{esc(beneficiary)}</strong></p>"
        )
    if bank_name:
        lines.append(
            f'<p style="margin: 4px 0 0; font-size: 13px; color: #166534;">Entidad: '
            f"{esc(bank_name)}</p>"
        )
    if iban:
        lines.append(
            f'<p style="margin: 4px 0 0; font-size: 13px; color: #166534;">IBAN: '
            f'<span style="font-family: monospace;">{esc(iban)}</span></p>'
        )
    if swift:
        lines.append(
            f'<p style="margin: 4px 0 0; font-size: 13px; color: #166534;">SWIFT/BIC: '
            f'<span style="font-family: monospace;">{esc(swift)}</span></p>'
        )
    if not iban:
        lines.append(
            '<p style="margin: 8px 0 0; font-size: 13px; color: #166534;">'
            "Te enviaremos los datos bancarios completos si aún no los tienes.</p>"
        )
    lines.append(
        '<p style="margin: 10px 0 0; font-size: 13px; color: #166534;">'
        "El pedido se preparará al recibir el pago.</p>"
    )
    return email_info_box("".join(lines))


def build_order_confirmation_html(
    pedido: PedidoOut,
    recipient_name: str,
) -> str:
    display_name = (recipient_name or "").strip() or "cliente"
    pedidos_url = f"{public_frontend_base()}/mi-cuenta/mis-pedidos"
    metodo = pedido.metodo_pago
    metodo_label = _METODO_PAGO_LABEL.get(metodo, str(metodo))
    envio_label = _TIPO_ENVIO_LABEL.get(pedido.tipo_envio, pedido.tipo_envio)
    addr = _shipping_address_html(pedido.direccion_snapshot)

    lines_html = "".join(_line_row_html(ln.line_data) for ln in pedido.lines)

    referencia_row = ""
    if pedido.referencia_pedido_cliente:
        referencia_row = (
            f'<tr><td style="padding: 4px 0; color: #64748b;">Tu referencia</td>'
            f'<td style="padding: 4px 0; text-align: right;">'
            f"{esc(pedido.referencia_pedido_cliente)}</td></tr>"
        )
    notas_block = ""
    if pedido.notas_pedido:
        notas_block = (
            f'<p style="margin: 16px 0 0; font-size: 13px; color: #64748b;">'
            f"<strong>Notas:</strong> {esc(pedido.notas_pedido)}</p>"
        )

    transfer_block = ""
    if metodo == MetodoPago.TRANSFER:
        transfer_block = _transfer_block_html(pedido)

    body = f"""
      <p style="margin: 0 0 16px; font-size: 15px; color: #0f172a;">
        Hemos registrado tu pedido <strong>{esc(pedido.ticket_number)}</strong>.
        Esta es la copia con el detalle de tu compra.
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size: 14px; margin-bottom: 8px;">
        <tr>
          <td style="padding: 4px 0; color: #64748b;">Fecha</td>
          <td style="padding: 4px 0; text-align: right;">{esc(_format_datetime(pedido.created_at))}</td>
        </tr>
        <tr>
          <td style="padding: 4px 0; color: #64748b;">Pago</td>
          <td style="padding: 4px 0; text-align: right;">{esc(metodo_label)}</td>
        </tr>
        <tr>
          <td style="padding: 4px 0; color: #64748b;">Envío</td>
          <td style="padding: 4px 0; text-align: right;">{esc(envio_label)}</td>
        </tr>
        {referencia_row}
      </table>
      {"<p style='margin: 12px 0 0; font-size: 13px; color: #64748b;'><strong>Dirección:</strong><br />" + addr + "</p>" if addr else ""}
      {transfer_block}
      <p style="margin: 24px 0 8px; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b;">Artículos</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size: 14px;">
        {lines_html}
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top: 16px; font-size: 14px;">
        <tr>
          <td style="padding: 6px 0; color: #64748b;">Subtotal (sin IVA)</td>
          <td style="padding: 6px 0; text-align: right;">{esc(_format_eur(pedido.subtotal_sin_iva))}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b;">Envío (sin IVA)</td>
          <td style="padding: 6px 0; text-align: right;">{esc(_format_eur(pedido.envio_sin_iva))}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b;">IVA</td>
          <td style="padding: 6px 0; text-align: right;">{esc(_format_eur(pedido.iva_importe))}</td>
        </tr>
        <tr>
          <td style="padding: 10px 0 0; font-size: 16px; font-weight: 700;">Total</td>
          <td style="padding: 10px 0 0; text-align: right; font-size: 16px; font-weight: 700;">{esc(_format_eur(pedido.total))}</td>
        </tr>
      </table>
      {notas_block}
      {email_button(pedidos_url, "Ver mis pedidos")}
      {email_muted_paragraph("Si el botón no funciona, entra en tu área profesional → Mis pedidos.")}
    """

    return render_cerpal_email(
        title="Confirmación de pedido",
        greeting=display_name,
        body_html=body,
    )


def _order_notify_recipients() -> list[str]:
    raw = os.getenv("MAIL_ORDER_NOTIFY", "").strip()
    if not raw:
        return []
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


async def send_order_confirmation_email(
    to_email: str,
    recipient_name: str,
    pedido: PedidoOut,
) -> None:
    if not is_mail_configured():
        logger.warning(
            "Pedido %s registrado pero SMTP no configurado; no se envía copia por correo.",
            pedido.ticket_number,
        )
        return

    subject = f"Pedido {pedido.ticket_number} — CERPAL"
    body = build_order_confirmation_html(pedido, recipient_name)
    ok = await send_mail_message(
        MessageSchema(
            subject=subject,
            recipients=[to_email.strip().lower()],
            body=body,
            subtype=MessageType.html,
        )
    )
    if not ok:
        logger.error(
            "No se pudo enviar la copia del pedido %s a %s.",
            pedido.ticket_number,
            to_email,
        )

    notify = [
        addr for addr in _order_notify_recipients()
        if addr and addr != to_email.strip().lower()
    ]
    if notify:
        await send_mail_message(
            MessageSchema(
                subject=f"Copia interna — {subject}",
                recipients=notify,
                body=body,
                subtype=MessageType.html,
            )
        )
