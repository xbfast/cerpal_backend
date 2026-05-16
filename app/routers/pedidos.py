import logging

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import AuthAccount, Pedido
from app.cart_schemas import CartLineItem
from app.order_schemas import (
    PedidoCreateIn,
    PedidoLineOut,
    PedidoListOut,
    PedidoOut,
)
from app.emails.order_confirmation import send_order_confirmation_email
from app.order_service import create_order_from_cart

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/me/pedidos", tags=["pedidos"])


def _tipo_envio_from_snapshot(snapshot: dict) -> Literal["delivery", "warehouse"]:
    tipo = snapshot.get("tipo_envio", "delivery")
    if tipo in ("delivery", "warehouse"):
        return tipo
    return "delivery"


def _pedido_lines(pedido: Pedido) -> list[CartLineItem]:
    out: list[CartLineItem] = []
    for ln in sorted(pedido.lines, key=lambda x: x.line_index):
        data = ln.line_data if isinstance(ln.line_data, dict) else {}
        out.append(CartLineItem.model_validate(data))
    return out


def _pedido_to_list_out(pedido: Pedido) -> PedidoListOut:
    snapshot = pedido.direccion_snapshot if isinstance(pedido.direccion_snapshot, dict) else {}
    lines = _pedido_lines(pedido)
    return PedidoListOut(
        id=pedido.id,
        ticket_number=pedido.ticket_number,
        created_at=pedido.created_at,
        metodo_pago=pedido.metodo_pago,
        estado_pago=pedido.estado_pago,
        estado_envio=pedido.estado_envio,
        tipo_envio=_tipo_envio_from_snapshot(snapshot),
        referencia_pedido_cliente=pedido.referencia_pedido_cliente,
        total=pedido.total,
        moneda=pedido.moneda,
        line_count=len(pedido.lines),
        lines=lines,
    )


def _pedido_to_out(pedido: Pedido) -> PedidoOut:
    snapshot = pedido.direccion_snapshot if isinstance(pedido.direccion_snapshot, dict) else {}
    return PedidoOut(
        id=pedido.id,
        ticket_number=pedido.ticket_number,
        created_at=pedido.created_at,
        metodo_pago=pedido.metodo_pago,
        estado_pago=pedido.estado_pago,
        estado_envio=pedido.estado_envio,
        tipo_envio=_tipo_envio_from_snapshot(snapshot),
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


@router.get("", response_model=list[PedidoListOut])
def listar_pedidos(
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PedidoListOut]:
    rows = db.scalars(
        select(Pedido)
        .where(Pedido.auth_id == user.id)
        .options(selectinload(Pedido.lines))
        .order_by(Pedido.created_at.desc())
    ).all()
    return [_pedido_to_list_out(p) for p in rows]


@router.post("", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def crear_pedido(
    payload: PedidoCreateIn,
    background_tasks: BackgroundTasks,
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
    pedido_out = _pedido_to_out(loaded)
    display = (user.nombre_responsable or user.nombre_empresa or "").strip()
    background_tasks.add_task(
        send_order_confirmation_email,
        user.email,
        display,
        pedido_out,
    )
    return pedido_out
