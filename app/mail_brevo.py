"""Envío transaccional vía API HTTPS de Brevo (sin SMTP saliente)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class BrevoConfig:
    api_key: str
    mail_from: str
    mail_from_name: str | None
    api_url: str
    timeout: float


def build_brevo_config() -> BrevoConfig | None:
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    if not api_key:
        return None

    username = os.getenv("MAIL_USERNAME", "").strip()
    mail_from = os.getenv("MAIL_FROM", username).strip()
    if not mail_from:
        logger.warning(
            "BREVO_API_KEY definido pero falta MAIL_FROM; correo desactivado."
        )
        return None

    from_name = os.getenv("MAIL_FROM_NAME", "").strip() or None
    api_url = os.getenv("BREVO_API_URL", BREVO_SEND_URL).strip() or BREVO_SEND_URL

    try:
        timeout = float(os.getenv("MAIL_TIMEOUT", "30").strip())
    except ValueError:
        timeout = 30.0
    timeout = max(5.0, min(timeout, 120.0))

    return BrevoConfig(
        api_key=api_key,
        mail_from=mail_from,
        mail_from_name=from_name,
        api_url=api_url,
        timeout=timeout,
    )


def normalize_recipients(recipients: list) -> list[str]:
    out: list[str] = []
    for item in recipients:
        email = getattr(item, "email", None)
        if email is not None:
            addr = str(email).strip()
        else:
            addr = str(item).strip()
        if addr and addr not in out:
            out.append(addr)
    return out


async def send_brevo_message(
    conf: BrevoConfig,
    *,
    subject: str,
    recipients: list,
    html_body: str,
) -> None:
    to_addrs = normalize_recipients(recipients)
    if not to_addrs:
        raise ValueError("No hay destinatarios para el correo.")

    sender: dict[str, str] = {"email": conf.mail_from}
    if conf.mail_from_name:
        sender["name"] = conf.mail_from_name

    payload = {
        "sender": sender,
        "to": [{"email": addr} for addr in to_addrs],
        "subject": subject,
        "htmlContent": html_body,
    }

    logger.info(
        "Enviando correo vía Brevo API → %s (asunto=%r).",
        to_addrs,
        subject,
    )

    async with httpx.AsyncClient(timeout=conf.timeout) as client:
        response = await client.post(
            conf.api_url,
            json=payload,
            headers={
                "api-key": conf.api_key,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
        )

    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(
            f"Brevo API {response.status_code}: {detail}"
        )

    logger.info("Brevo aceptó el envío (status %s).", response.status_code)
