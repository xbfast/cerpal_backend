"""Lógica de creación de pedidos desde el carrito."""

from datetime import datetime
from decimal import Decimal
import uuid
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.cart_schemas import CartLineItem
from app.models import Cart, CartLine, Direccion, Pedido, PedidoLine, PedidoTicketSeq
from app.order_enums import EstadoEnvio, EstadoPago, MetodoPago
from app.order_schemas import PedidoCreateIn

FREE_SHIPPING_THRESHOLD_EUR = Decimal("220")
SHIPPING_FLAT_EUR = Decimal("15")
IVA_RATE = Decimal("0.21")
MONEY_TOLERANCE = Decimal("0.02")

WAREHOUSE_ADDRESS_SNAPSHOT: dict = {
    "tipo_envio": "warehouse",
    "name": "Cerpal · Almacén central",
    "direccion": "Recogida en instalaciones Cerpal",
    "cp": "",
    "ciudad": "",
    "provincia": "",
    "telefono": None,
    "persona_contacto": None,
    "email": None,
}


def money2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def cart_subtotal_from_lines(lines: list[CartLineItem]) -> Decimal:
    total = Decimal("0")
    for line in lines:
        qty = line.quantity
        total += Decimal(str(line.price_per_unit)) * qty
    return money2(total)


def shipping_ex_vat(tipo_envio: str, subtotal: Decimal) -> Decimal:
    if tipo_envio == "warehouse":
        return Decimal("0")
    if subtotal >= FREE_SHIPPING_THRESHOLD_EUR:
        return Decimal("0")
    return SHIPPING_FLAT_EUR


def totals_from_cart(tipo_envio: str, lines: list[CartLineItem]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    subtotal = cart_subtotal_from_lines(lines)
    envio = money2(shipping_ex_vat(tipo_envio, subtotal))
    base = money2(subtotal + envio)
    iva = money2(base * IVA_RATE)
    total = money2(base + iva)
    return subtotal, envio, iva, total


def assert_totals_match(payload: PedidoCreateIn, expected: tuple[Decimal, Decimal, Decimal, Decimal]) -> None:
    exp_sub, exp_env, exp_iva, exp_total = expected
    pairs = (
        (payload.subtotal_sin_iva, exp_sub),
        (payload.envio_sin_iva, exp_env),
        (payload.iva_importe, exp_iva),
        (payload.total, exp_total),
    )
    for sent, exp in pairs:
        if abs(Decimal(str(sent)) - exp) > MONEY_TOLERANCE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Los importes del pedido no coinciden. Actualiza el checkout e inténtalo de nuevo.",
            )


def next_ticket_number(db: Session) -> str:
    year = datetime.now().year
    seq = db.get(PedidoTicketSeq, year)
    if seq is None:
        seq = PedidoTicketSeq(year=year, last_number=0)
        db.add(seq)
        db.flush()
    seq.last_number = int(seq.last_number) + 1
    db.flush()
    return f"{year}-{seq.last_number:06d}"


def redsys_order_from_ticket(ticket_number: str) -> str:
    """Redsys exige un identificador corto (4-12 caracteres, iniciando por números)."""
    digits = "".join(ch for ch in ticket_number if ch.isdigit())
    if len(digits) < 4:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo generar la referencia Redsys del pedido.",
        )
    return digits[:12]


def direccion_to_snapshot(d: Direccion) -> dict:
    return {
        "tipo_envio": "delivery",
        "direccion_id": str(d.id),
        "name": d.name,
        "direccion": d.direccion,
        "cp": d.cp,
        "ciudad": d.ciudad,
        "provincia": d.provincia,
        "telefono": d.telefono,
        "persona_contacto": d.persona_contacto,
        "email": d.email,
    }


def resolve_direccion_snapshot(
    db: Session,
    auth_id: UUID,
    tipo_envio: str,
    direccion_id: UUID | None,
) -> tuple[UUID | None, dict]:
    if tipo_envio == "warehouse":
        return None, dict(WAREHOUSE_ADDRESS_SNAPSHOT)
    if direccion_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selecciona una dirección de envío.",
        )
    direccion = db.scalar(
        select(Direccion).where(
            Direccion.id == direccion_id,
            Direccion.auth_id == auth_id,
        )
    )
    if direccion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dirección no encontrada.",
        )
    return direccion.id, direccion_to_snapshot(direccion)


def load_cart_lines(db: Session, auth_id: UUID) -> list[CartLineItem]:
    cart = db.scalar(select(Cart).where(Cart.auth_id == auth_id))
    if cart is None:
        return []
    rows = db.scalars(
        select(CartLine)
        .where(CartLine.cart_id == cart.id)
        .order_by(CartLine.line_index.asc())
    ).all()
    out: list[CartLineItem] = []
    for row in rows:
        out.append(CartLineItem.model_validate(row.line_data))
    return out


def clear_user_cart(db: Session, auth_id: UUID) -> None:
    cart = db.scalar(select(Cart).where(Cart.auth_id == auth_id))
    if cart is None:
        return
    db.execute(delete(CartLine).where(CartLine.cart_id == cart.id))
    db.delete(cart)


def create_order_from_cart(
    db: Session,
    auth_id: UUID,
    payload: PedidoCreateIn,
) -> Pedido:
    if payload.metodo_pago not in (MetodoPago.TRANSFER, MetodoPago.CARD):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Método de pago no disponible.",
        )

    cart_items = load_cart_lines(db, auth_id)
    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El carrito está vacío.",
        )

    expected = totals_from_cart(payload.tipo_envio, cart_items)
    assert_totals_match(payload, expected)
    subtotal, envio, iva, total = expected

    direccion_id, snapshot = resolve_direccion_snapshot(
        db,
        auth_id,
        payload.tipo_envio,
        payload.direccion_id,
    )

    ticket_number = next_ticket_number(db)
    redsys_order_id = (
        redsys_order_from_ticket(ticket_number)
        if payload.metodo_pago == MetodoPago.CARD
        else None
    )

    pedido = Pedido(
        ticket_number=ticket_number,
        auth_id=auth_id,
        metodo_pago=str(payload.metodo_pago),
        estado_pago=str(EstadoPago.PENDIENTE),
        estado_envio=str(EstadoEnvio.PENDIENTE),
        redsys_order_id=redsys_order_id,
        direccion_id=direccion_id,
        direccion_snapshot=snapshot,
        referencia_pedido_cliente=payload.referencia_pedido_cliente,
        notas_pedido=payload.notas_pedido,
        subtotal_sin_iva=subtotal,
        envio_sin_iva=envio,
        iva_importe=iva,
        total=total,
    )
    db.add(pedido)
    db.flush()

    for idx, item in enumerate(cart_items):
        db.add(
            PedidoLine(
                id=uuid.uuid4(),
                pedido_id=pedido.id,
                line_index=idx,
                line_data=item.model_dump(mode="json"),
            )
        )

    if payload.metodo_pago == MetodoPago.TRANSFER:
        clear_user_cart(db, auth_id)
    db.commit()
    db.refresh(pedido)
    return pedido
