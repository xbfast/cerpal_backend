"""Carrito de compra por usuario (líneas persistidas).

Revision ID: 005_shopping_cart
Revises: 004_catalog_schema
Create Date: 2026-05-13

Tablas:
- cart: una fila por cuenta (auth_id único).
- cart_line: líneas ordenadas; snapshot JSONB alineado con el store del frontend.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_shopping_cart"
down_revision: Union[str, None] = "004_catalog_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cart",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["auth_id"], ["auth.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auth_id", name="uq_cart_auth_id"),
    )

    op.create_table(
        "cart_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cart_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_index", sa.SmallInteger(), nullable=False),
        sa.Column("line_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["cart_id"], ["cart.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cart_id", "line_index", name="uq_cart_line_cart_pos"),
    )
    op.create_index(op.f("ix_cart_line_cart_id"), "cart_line", ["cart_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cart_line_cart_id"), table_name="cart_line")
    op.drop_table("cart_line")
    op.drop_index(op.f("ix_cart_auth_id"), table_name="cart")
    op.drop_table("cart")
