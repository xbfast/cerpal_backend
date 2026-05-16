"""Pedidos: enums, cabecera `pedido`, líneas `pedido_line`, secuencia de ticket.

Revision ID: 006_orders
Revises: 005_shopping_cart
Create Date: 2026-05-16

Tablas:
- pedido_ticket_seq — numeración anual CERP-YYYY-NNNNNN
- pedido — cabecera (ticket, usuario, pago, envío, dirección, totales, notas checkout)
- pedido_line — líneas; `line_data` JSONB = snapshot del carrito (CartLineItem)

Enums PostgreSQL:
- order_payment_method (metodo_pago)
- order_payment_status (estado_pago)
- order_shipping_status (estado_envio)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_orders"
down_revision: Union[str, None] = "005_shopping_cart"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

METODO_PAGO_VALUES = ("card", "transfer")
ESTADO_PAGO_VALUES = (
    "pendiente",
    "pagado",
    "fallido",
    "reembolsado",
    "cancelado",
)
ESTADO_ENVIO_VALUES = (
    "pendiente",
    "preparando",
    "enviado",
    "entregado",
    "cancelado",
)


def _create_pg_enum(name: str, values: tuple[str, ...]) -> postgresql.ENUM:
    enum_type = postgresql.ENUM(*values, name=name, create_type=True)
    enum_type.create(op.get_bind(), checkfirst=True)
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    metodo_pago_enum = _create_pg_enum("order_payment_method", METODO_PAGO_VALUES)
    estado_pago_enum = _create_pg_enum("order_payment_status", ESTADO_PAGO_VALUES)
    estado_envio_enum = _create_pg_enum("order_shipping_status", ESTADO_ENVIO_VALUES)

    op.create_table(
        "pedido_ticket_seq",
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column(
            "last_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.PrimaryKeyConstraint("year"),
    )

    op.create_table(
        "pedido",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_number", sa.String(length=32), nullable=False),
        sa.Column("auth_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metodo_pago", metodo_pago_enum, nullable=False),
        sa.Column(
            "estado_pago",
            estado_pago_enum,
            nullable=False,
            server_default=sa.text("'pendiente'::order_payment_status"),
        ),
        sa.Column(
            "estado_envio",
            estado_envio_enum,
            nullable=False,
            server_default=sa.text("'pendiente'::order_shipping_status"),
        ),
        sa.Column("direccion_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "direccion_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("subtotal_sin_iva", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "envio_sin_iva",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("iva_importe", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "moneda",
            sa.String(length=3),
            nullable=False,
            server_default=sa.text("'EUR'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["auth_id"], ["auth.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["direccion_id"],
            ["direcciones.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_number", name="uq_pedido_ticket_number"),
    )
    op.create_index(op.f("ix_pedido_auth_id"), "pedido", ["auth_id"], unique=False)
    op.create_index(
        op.f("ix_pedido_estado_pago"), "pedido", ["estado_pago"], unique=False
    )
    op.create_index(
        op.f("ix_pedido_estado_envio"), "pedido", ["estado_envio"], unique=False
    )
    op.create_index(
        op.f("ix_pedido_created_at"), "pedido", ["created_at"], unique=False
    )

    op.create_table(
        "pedido_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pedido_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_index", sa.SmallInteger(), nullable=False),
        sa.Column("line_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedido.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pedido_id", "line_index", name="uq_pedido_line_pedido_pos"),
    )
    op.create_index(
        op.f("ix_pedido_line_pedido_id"), "pedido_line", ["pedido_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pedido_line_pedido_id"), table_name="pedido_line")
    op.drop_table("pedido_line")
    op.drop_index(op.f("ix_pedido_created_at"), table_name="pedido")
    op.drop_index(op.f("ix_pedido_estado_envio"), table_name="pedido")
    op.drop_index(op.f("ix_pedido_estado_pago"), table_name="pedido")
    op.drop_index(op.f("ix_pedido_auth_id"), table_name="pedido")
    op.drop_table("pedido")
    op.drop_table("pedido_ticket_seq")
    op.execute("DROP TYPE IF EXISTS order_shipping_status")
    op.execute("DROP TYPE IF EXISTS order_payment_status")
    op.execute("DROP TYPE IF EXISTS order_payment_method")
