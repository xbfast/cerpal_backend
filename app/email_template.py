"""Plantilla HTML única para todos los correos transaccionales de CERPAL."""

from __future__ import annotations

import html
import os

# Alineado con la UI (oscuro / botones)
_COLOR_OSCURO = "#121A2E"
_COLOR_CLARO = "#4A5565"
_COLOR_BORDER = "#E5E7EB"
_COLOR_BG = "#F8FAFC"
_COLOR_WHITE = "#FFFFFF"


def esc(value: object) -> str:
    return html.escape(str(value) if value is not None else "", quote=True)


def public_frontend_base() -> str:
    return os.getenv("PUBLIC_FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")


def render_cerpal_email(
    *,
    title: str,
    greeting: str,
    body_html: str,
    footer_note: str | None = None,
) -> str:
    """
    Envuelve el contenido en el layout CERPAL (cabecera, saludo, pie).

    `body_html` debe ser HTML seguro (usar `esc()` para datos de usuario).
    """
    safe_title = esc(title)
    safe_greeting = esc(greeting)
    footer = (
        f'<p style="margin: 16px 0 0; font-size: 13px; color: {_COLOR_CLARO};">'
        f"{esc(footer_note)}</p>"
        if footer_note
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
</head>
<body style="margin: 0; padding: 0; background: {_COLOR_BG}; font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; line-height: 1.5; color: {_COLOR_OSCURO};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: {_COLOR_BG}; padding: 24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width: 560px; background: {_COLOR_WHITE}; border-radius: 16px; border: 1px solid {_COLOR_BORDER}; overflow: hidden;">
          <tr>
            <td style="background: {_COLOR_OSCURO}; padding: 20px 28px;">
              <p style="margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0.04em; color: #fff;">CERPAL</p>
              <p style="margin: 6px 0 0; font-size: 13px; color: #94a3b8;">{safe_title}</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px;">
              <p style="margin: 0 0 16px; font-size: 16px;">{safe_greeting},</p>
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="padding: 0 28px 24px; border-top: 1px solid {_COLOR_BORDER};">
              <p style="margin: 16px 0 0; font-size: 13px; color: {_COLOR_CLARO};">
                Este mensaje se ha enviado desde CERPAL. Si tienes dudas, escríbenos a
                <a href="mailto:info@cerpal.es" style="color: {_COLOR_OSCURO};">info@cerpal.es</a>.
              </p>
              {footer}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def email_button(href: str, label: str) -> str:
    safe_href = esc(href)
    safe_label = esc(label)
    return (
        f'<p style="margin: 24px 0;">'
        f'<a href="{safe_href}" style="display: inline-block; padding: 12px 24px; '
        f"background: {_COLOR_OSCURO}; color: #fff; text-decoration: none; "
        f'border-radius: 10px; font-weight: 600;">{safe_label}</a></p>'
    )


def email_muted_paragraph(text: str) -> str:
    return (
        f'<p style="margin: 12px 0 0; font-size: 14px; color: {_COLOR_CLARO};">'
        f"{esc(text)}</p>"
    )


def email_info_box(inner_html: str) -> str:
    return (
        f'<div style="margin: 20px 0; padding: 16px; background: #f0fdf4; '
        f'border: 1px solid #bbf7d0; border-radius: 12px;">{inner_html}</div>'
    )
