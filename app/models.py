import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.order_enums import EstadoEnvio, EstadoPago, MetodoPago

# Tipo nativo en PostgreSQL; el DDL lo crea Alembic (`create_type=False`).
USER_ROLE_ENUM = PG_ENUM(
    "cliente",
    "comercial",
    "administrador",
    name="user_role",
    create_type=False,
)

METODO_PAGO_ENUM = PG_ENUM(
    MetodoPago.CARD,
    MetodoPago.TRANSFER,
    name="order_payment_method",
    create_type=False,
)

ESTADO_PAGO_ENUM = PG_ENUM(
    EstadoPago.PENDIENTE,
    EstadoPago.PAGADO,
    EstadoPago.FALLIDO,
    EstadoPago.REEMBOLSADO,
    EstadoPago.CANCELADO,
    name="order_payment_status",
    create_type=False,
)

ESTADO_ENVIO_ENUM = PG_ENUM(
    EstadoEnvio.PENDIENTE,
    EstadoEnvio.PREPARANDO,
    EstadoEnvio.ENVIADO,
    EstadoEnvio.ENTREGADO,
    EstadoEnvio.CANCELADO,
    name="order_shipping_status",
    create_type=False,
)


class AuthAccount(Base):
    __tablename__ = "auth"

    # UUID en Python antes del INSERT (si solo server_default, id queda None y refresh() rompe)
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    nombre_empresa: Mapped[str] = mapped_column(String(255))
    cif_nif: Mapped[str] = mapped_column(String(20), unique=True)
    nombre_responsable: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    telefono: Mapped[str] = mapped_column(String(20))
    direccion: Mapped[str] = mapped_column(Text)
    cp: Mapped[str] = mapped_column(String(10))
    ciudad: Mapped[str] = mapped_column(String(100))
    provincia: Mapped[str] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sitio_web: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_facturas: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    validado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    email_verificado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    rol: Mapped[str] = mapped_column(
        USER_ROLE_ENUM,
        nullable=False,
        server_default=text("'cliente'::user_role"),
        default="cliente",
    )
    # TIMESTAMP sin zona (igual que CREATE TABLE … TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )
    password_reset_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    contacts: Mapped[list["Contact"]] = relationship(
        "Contact",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    direcciones: Mapped[list["Direccion"]] = relationship(
        "Direccion",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    cart: Mapped["Cart | None"] = relationship(
        "Cart",
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
    )
    pedidos: Mapped[list["Pedido"]] = relationship(
        "Pedido",
        back_populates="account",
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    auth_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("auth.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_contacto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_directo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["AuthAccount"] = relationship(
        "AuthAccount", back_populates="contacts"
    )


class Direccion(Base):
    """Filas en `direcciones` (ver `sql/create_direcciones_table.sql`)."""

    __tablename__ = "direcciones"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    auth_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("auth.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    direccion: Mapped[str] = mapped_column(Text, nullable=False)
    cp: Mapped[str] = mapped_column(String(10), nullable=False)
    ciudad: Mapped[str] = mapped_column(String(100), nullable=False)
    provincia: Mapped[str] = mapped_column(String(100), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    persona_contacto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        "default",
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["AuthAccount"] = relationship(
        "AuthAccount", back_populates="direcciones"
    )
    pedidos: Mapped[list["Pedido"]] = relationship("Pedido", back_populates="direccion")


class PedidoTicketSeq(Base):
    """Contador anual para `ticket_number` (CERP-YYYY-NNNNNN)."""

    __tablename__ = "pedido_ticket_seq"

    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_number: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))


class Pedido(Base):
    """Pedido confirmado (snapshot de carrito + dirección + totales)."""

    __tablename__ = "pedido"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticket_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    auth_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("auth.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    metodo_pago: Mapped[str] = mapped_column(METODO_PAGO_ENUM, nullable=False)
    estado_pago: Mapped[str] = mapped_column(
        ESTADO_PAGO_ENUM,
        nullable=False,
        server_default=text("'pendiente'::order_payment_status"),
        default=EstadoPago.PENDIENTE,
        index=True,
    )
    estado_envio: Mapped[str] = mapped_column(
        ESTADO_ENVIO_ENUM,
        nullable=False,
        server_default=text("'pendiente'::order_shipping_status"),
        default=EstadoEnvio.PENDIENTE,
        index=True,
    )
    direccion_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("direcciones.id", ondelete="SET NULL"),
        nullable=True,
    )
    direccion_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    referencia_pedido_cliente: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    notas_pedido: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtotal_sin_iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    envio_sin_iva: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("0"),
        default=Decimal("0"),
    )
    iva_importe: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default=text("'EUR'"),
        default="EUR",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["AuthAccount"] = relationship("AuthAccount", back_populates="pedidos")
    direccion: Mapped["Direccion | None"] = relationship(
        "Direccion", back_populates="pedidos"
    )
    lines: Mapped[list["PedidoLine"]] = relationship(
        "PedidoLine",
        back_populates="pedido",
        cascade="all, delete-orphan",
        order_by="PedidoLine.line_index",
    )


class PedidoLine(Base):
    """Línea de pedido: mismo JSON que `cart_line.line_data` (CartLineItem)."""

    __tablename__ = "pedido_line"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    pedido_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pedido.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    line_data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    pedido: Mapped["Pedido"] = relationship("Pedido", back_populates="lines")


class Cart(Base):
    """Un carrito por cuenta (`auth_id` único)."""

    __tablename__ = "cart"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    auth_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("auth.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["AuthAccount"] = relationship("AuthAccount", back_populates="cart")
    lines: Mapped[list["CartLine"]] = relationship(
        "CartLine",
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartLine.line_index",
    )


class CartLine(Base):
    """Línea de carrito: `id` coincide con el UUID de línea del cliente."""

    __tablename__ = "cart_line"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    cart_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cart.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    line_data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    cart: Mapped["Cart"] = relationship("Cart", back_populates="lines")


# Re-export enums for routers/schemas
__all__ = [
    "AuthAccount",
    "Cart",
    "CartLine",
    "Contact",
    "Direccion",
    "EstadoEnvio",
    "EstadoPago",
    "MetodoPago",
    "Pedido",
    "PedidoLine",
    "PedidoTicketSeq",
]
