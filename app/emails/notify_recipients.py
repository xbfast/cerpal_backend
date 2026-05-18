"""Destinatarios internos de copia (MAIL_ORDER_NOTIFY)."""

from __future__ import annotations

import os


def order_notify_recipients() -> list[str]:
    raw = os.getenv("MAIL_ORDER_NOTIFY", "").strip()
    if not raw:
        return []
    return [e.strip().lower() for e in raw.split(",") if e.strip()]
