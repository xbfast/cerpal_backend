"""Esquemas de pedido (API / checkout)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.cart_schemas import CartLineItem
from app.order_enums import EstadoEnvio, EstadoPago, MetodoPago


class PedidoCreateIn(BaseModel):
    """Payload al confirmar checkout."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tipo_envio: Literal["delivery", "warehouse"] = "delivery"
    direccion_id: UUID | None = None
    metodo_pago: MetodoPago
    referencia_pedido_cliente: str | None = Field(None, max_length=128)
    notas_pedido: str | None = Field(None, max_length=4000)
    subtotal_sin_iva: Decimal = Field(..., ge=0, decimal_places=2)
    envio_sin_iva: Decimal = Field(..., ge=0, decimal_places=2)
    iva_importe: Decimal = Field(..., ge=0, decimal_places=2)
    total: Decimal = Field(..., ge=0, decimal_places=2)

    @field_validator(
        "referencia_pedido_cliente",
        "notas_pedido",
        mode="before",
    )
    @classmethod
    def opcional_vacio_a_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def direccion_requerida_en_domicilio(self) -> Self:
        if self.tipo_envio == "delivery" and self.direccion_id is None:
            raise ValueError("direccion_id es obligatoria para envío a domicilio.")
        return self


class PedidoListOut(BaseModel):
    """Pedido en listado (historial del cliente)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_number: str
    created_at: datetime
    metodo_pago: MetodoPago
    estado_pago: EstadoPago
    estado_envio: EstadoEnvio
    tipo_envio: Literal["delivery", "warehouse"] = "delivery"
    referencia_pedido_cliente: str | None
    total: Decimal
    moneda: str
    line_count: int = Field(..., ge=0)
    lines: list[CartLineItem] = Field(default_factory=list)


class PedidoLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_index: int
    line_data: CartLineItem


class RedsysPaymentOut(BaseModel):
    action: str
    Ds_SignatureVersion: str
    Ds_MerchantParameters: str
    Ds_Signature: str


class PedidoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_number: str
    created_at: datetime
    metodo_pago: MetodoPago
    estado_pago: EstadoPago
    estado_envio: EstadoEnvio
    tipo_envio: Literal["delivery", "warehouse"] = "delivery"
    referencia_pedido_cliente: str | None
    notas_pedido: str | None
    subtotal_sin_iva: Decimal
    envio_sin_iva: Decimal
    iva_importe: Decimal
    total: Decimal
    moneda: str
    direccion_snapshot: dict
    lines: list[PedidoLineOut] = Field(default_factory=list)
    redsys_payment: RedsysPaymentOut | None = None
