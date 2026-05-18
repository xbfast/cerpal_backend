"""
Envío de prueba (Brevo API o SMTP). Uso desde la raíz del backend:

  python -m app.send_test_mail
  python -m app.send_test_mail otro@dominio.com

En Docker (variables ya inyectadas por compose):

  docker compose exec api python -m app.send_test_mail
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi_mail import MessageSchema, MessageType

# Misma ruta que `app/database.py` para `.env` local
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def _run(recipient: str) -> int:
    from app.mail import get_mail_provider, init_mail, is_mail_configured, send_mail_message

    init_mail()
    if not is_mail_configured():
        logging.error(
            "Correo no configurado: BREVO_API_KEY + MAIL_FROM, o SMTP (MAIL_SERVER, …)."
        )
        return 1

    provider = get_mail_provider() or "?"
    logging.info("Proveedor: %s. Enviando correo de prueba a %s…", provider, recipient)
    ok = await send_mail_message(
        MessageSchema(
            subject=f"Prueba Cerpal ({provider})",
            recipients=[recipient],
            body=(
                "<p>Este es un correo de prueba enviado desde el backend Cerpal.</p>"
                f"<p>Proveedor: <strong>{provider}</strong></p>"
            ),
            subtype=MessageType.html,
        )
    )
    if ok:
        logging.info("Enviado correctamente (%s) a %s.", provider, recipient)
        return 0
    logging.error("Fallo al enviar a %s (revisa logs anteriores).", recipient)
    return 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="Envía un correo de prueba (Brevo o SMTP) según .env."
    )
    p.add_argument(
        "recipient",
        nargs="?",
        default="hola@mvisual.es",
        help="Destinatario (por defecto: hola@mvisual.es)",
    )
    args = p.parse_args()
    code = asyncio.run(_run(args.recipient.strip()))
    sys.exit(code)


if __name__ == "__main__":
    main()
