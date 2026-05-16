"""Esquemas de pedido (API / checkout)."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.cart_schemas import CartLineItem
from app.order_enums import EstadoEnvio, EstadoPago, MetodoPago


class PedidoCreateIn(BaseModel):
    """Payload al confirmar checkout (totales calculados en servidor recomendado)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    direccion_id: UUID
    metodo_pago: MetodoPago
    referencia_pedido_cliente: str | None = Field(None, max_length=128)
    notas_pedido: str | None = Field(None, max_length=4000)
    subtotal_sin_iva: Decimal = Field(..., ge=0, decimal_places=2)
    envio_sin_iva: Decimal = Field(..., ge=0, decimal_places=2)
    iva_importe: Decimal = Field(..., ge=0, decimal_places=2)
    total: Decimal = Field(..., ge=0, decimal_places=2)


class PedidoLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_index: int
    line_data: CartLineItem


class PedidoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_number: str
    metodo_pago: MetodoPago
    estado_pago: EstadoPago
    estado_envio: EstadoEnvio
    referencia_pedido_cliente: str | None
    notas_pedido: str | None
    subtotal_sin_iva: Decimal
    envio_sin_iva: Decimal
    iva_importe: Decimal
    total: Decimal
    moneda: str
    lines: list[PedidoLineOut] = Field(default_factory=list)
