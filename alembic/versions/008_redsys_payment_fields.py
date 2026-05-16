"""Campos Redsys en pedido.

Revision ID: 008_redsys_payment_fields
Revises: 007_pedido_notas
Create Date: 2026-05-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_redsys_payment_fields"
down_revision: Union[str, None] = "007_pedido_notas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pedido", sa.Column("redsys_order_id", sa.String(length=12), nullable=True))
    op.add_column(
        "pedido",
        sa.Column("redsys_authorization_code", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "pedido",
        sa.Column("redsys_response_code", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "pedido",
        sa.Column("redsys_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(op.f("ix_pedido_redsys_order_id"), "pedido", ["redsys_order_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_pedido_redsys_order_id"), table_name="pedido")
    op.drop_column("pedido", "redsys_payload")
    op.drop_column("pedido", "redsys_response_code")
    op.drop_column("pedido", "redsys_authorization_code")
    op.drop_column("pedido", "redsys_order_id")
