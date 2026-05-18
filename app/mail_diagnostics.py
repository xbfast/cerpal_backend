"""Resumen de configuración SMTP (sin secretos) para logs y /health/mail."""

from __future__ import annotations

import os
from typing import Any

from app.mail import build_connection_config, is_mail_configured


def mail_diagnostic_summary() -> dict[str, Any]:
    """Estado SMTP visible en logs o health check (nunca incluye contraseñas)."""
    server = os.getenv("MAIL_SERVER", "").strip()
    if not server:
        return {
            "configured": False,
            "reason": "MAIL_SERVER vacío en el entorno del proceso",
        }

    conf = build_connection_config()
    if conf is None:
        return {
            "configured": False,
            "reason": "MAIL_SERVER definido pero la configuración SMTP no es válida",
            "mail_server": server,
        }

    frontend = os.getenv("PUBLIC_FRONTEND_URL", "").strip() or None
    return {
        "configured": is_mail_configured(),
        "mail_server": conf.MAIL_SERVER,
        "mail_port": conf.MAIL_PORT,
        "mail_from": str(conf.MAIL_FROM),
        "mail_username": str(conf.MAIL_USERNAME),
        "mail_starttls": conf.MAIL_STARTTLS,
        "mail_ssl_tls": conf.MAIL_SSL_TLS,
        "public_frontend_url": frontend,
    }
