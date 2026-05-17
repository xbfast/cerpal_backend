import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.emails.order_confirmation import send_order_confirmation_email
from app.models import Pedido
from app.order_enums import EstadoPago
from app.order_service import clear_user_cart
from app.payments.redsys import response_is_paid, validate_notification_signature
from app.routers.pedidos import _pedido_to_out

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pagos/redsys", tags=["redsys"])


def _pick(params: dict, *names: str) -> str:
    for name in names:
        value = params.get(name)
        if value is not None:
            return str(value).strip()
    return ""


@router.post("/notification")
async def redsys_notification(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    raw = (await request.body()).decode("utf-8")
    form = {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    merchant_parameters = form.get("Ds_MerchantParameters", "")
    signature = form.get("Ds_Signature", "").replace(" ", "+")
    if not merchant_parameters or not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notificación Redsys incompleta.",
        )

    params = validate_notification_signature(
        merchant_parameters=merchant_parameters,
        signature=signature,
    )
    redsys_order = _pick(
        params, "Ds_Order", "DS_ORDER", "Ds_Merchant_Order", "DS_MERCHANT_ORDER"
    )
    response_code = _pick(params, "Ds_Response", "DS_RESPONSE")
    auth_code = _pick(params, "Ds_AuthorisationCode", "DS_AUTHORISATIONCODE")

    pedido = db.scalar(
        select(Pedido)
        .where(Pedido.redsys_order_id == redsys_order)
        .options(selectinload(Pedido.lines), selectinload(Pedido.account))
    )
    if pedido is None:
        logger.warning("Notificación Redsys para pedido desconocido: %s", redsys_order)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido Redsys no encontrado.",
        )

    was_paid = pedido.estado_pago == EstadoPago.PAGADO
    paid = response_is_paid(params)
    pedido.redsys_response_code = response_code or None
    pedido.redsys_authorization_code = auth_code or None
    pedido.redsys_payload = params
    pedido.estado_pago = EstadoPago.PAGADO if (was_paid or paid) else EstadoPago.FALLIDO
    if paid and not was_paid:
        clear_user_cart(db, pedido.auth_id)
    db.commit()
    db.refresh(pedido)

    if paid and not was_paid:
        display = (
            pedido.account.nombre_responsable
            or pedido.account.nombre_empresa
            or ""
        ).strip()
        background_tasks.add_task(
            send_order_confirmation_email,
            pedido.account.email,
            display,
            _pedido_to_out(pedido),
        )

    return {"ok": True}
