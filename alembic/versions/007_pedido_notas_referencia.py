"""Referencia de cliente y notas del pedido (checkout).

Revision ID: 007_pedido_notas
Revises: 006_orders
Create Date: 2026-05-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_pedido_notas"
down_revision: Union[str, None] = "006_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedido",
        sa.Column("referencia_pedido_cliente", sa.String(length=128), nullable=True),
    )
    op.add_column("pedido", sa.Column("notas_pedido", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pedido", "notas_pedido")
    op.drop_column("pedido", "referencia_pedido_cliente")
