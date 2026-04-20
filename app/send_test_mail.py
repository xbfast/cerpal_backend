"""
Envío de prueba SMTP. Uso desde la raíz del backend:

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
    from app.mail import init_mail, is_mail_configured, send_mail_message

    init_mail()
    if not is_mail_configured():
        logging.error("SMTP no configurado (MAIL_SERVER vacío o credenciales incompletas).")
        return 1

    ok = await send_mail_message(
        MessageSchema(
            subject="Prueba Cerpal (SMTP)",
            recipients=[recipient],
            body=(
                "<p>Este es un correo de prueba enviado desde el backend Cerpal.</p>"
                "<p>Si lo recibes, el SMTP está operativo.</p>"
            ),
            subtype=MessageType.html,
        )
    )
    if ok:
        logging.info("Enviado correctamente (SMTP aceptó el mensaje) a %s.", recipient)
        return 0
    logging.error("Fallo al enviar a %s (revisa logs anteriores).", recipient)
    return 1


def main() -> None:
    p = argparse.ArgumentParser(description="Envía un correo de prueba vía SMTP configurado en .env.")
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
