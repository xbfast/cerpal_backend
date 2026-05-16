import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import AuthAccount, Pedido, PedidoLine
from app.cart_schemas import CartLineItem
from app.order_schemas import PedidoCreateIn, PedidoLineOut, PedidoOut
from app.order_service import create_order_from_cart

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/me/pedidos", tags=["pedidos"])


def _pedido_to_out(pedido: Pedido) -> PedidoOut:
    snapshot = pedido.direccion_snapshot if isinstance(pedido.direccion_snapshot, dict) else {}
    tipo_envio = snapshot.get("tipo_envio", "delivery")
    if tipo_envio not in ("delivery", "warehouse"):
        tipo_envio = "delivery"
    return PedidoOut(
        id=pedido.id,
        ticket_number=pedido.ticket_number,
        metodo_pago=pedido.metodo_pago,
        estado_pago=pedido.estado_pago,
        estado_envio=pedido.estado_envio,
        tipo_envio=tipo_envio,
        referencia_pedido_cliente=pedido.referencia_pedido_cliente,
        notas_pedido=pedido.notas_pedido,
        subtotal_sin_iva=pedido.subtotal_sin_iva,
        envio_sin_iva=pedido.envio_sin_iva,
        iva_importe=pedido.iva_importe,
        total=pedido.total,
        moneda=pedido.moneda,
        direccion_snapshot=snapshot,
        lines=[
            PedidoLineOut(
                id=ln.id,
                line_index=ln.line_index,
                line_data=CartLineItem.model_validate(ln.line_data),
            )
            for ln in sorted(pedido.lines, key=lambda x: x.line_index)
        ],
    )


@router.post("", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def crear_pedido(
    payload: PedidoCreateIn,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PedidoOut:
    try:
        pedido = create_order_from_cart(db, user.id, payload)
    except HTTPException:
        raise
    except DBAPIError as e:
        db.rollback()
        logger.exception("Error al crear pedido")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo registrar el pedido. Inténtalo de nuevo.",
        ) from e

    loaded = db.scalar(
        select(Pedido)
        .where(Pedido.id == pedido.id)
        .options(selectinload(Pedido.lines))
    )
    if loaded is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pedido creado pero no se pudo cargar la respuesta.",
        )
    return _pedido_to_out(loaded)
