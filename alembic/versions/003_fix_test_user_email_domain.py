"""Corrige email del usuario de prueba (.local no es válido para EmailStr / email-validator).

Si ya aplicaste 002 con test@cerpal.local, esta migración pasa a test@example.com.

Revision ID: 003_fix_test_user_email
Revises: 002_seed_test_user
Create Date: 2026-04-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_fix_test_user_email"
down_revision: Union[str, None] = "002_seed_test_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "test@cerpal.local"
_NEW = "test@example.com"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE auth SET email = :new WHERE lower(email) = lower(:old)"),
        {"old": _OLD, "new": _NEW},
    )
    bind.execute(
        sa.text("UPDATE direcciones SET email = :new WHERE lower(email) = lower(:old)"),
        {"old": _OLD, "new": _NEW},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE auth SET email = :old
            WHERE lower(email) = lower(:new) AND cif_nif = '12345678Z'
            """
        ),
        {"old": _OLD, "new": _NEW},
    )
    bind.execute(
        sa.text(
            """
            UPDATE direcciones SET email = :old
            WHERE lower(email) = lower(:new)
              AND auth_id IN (SELECT id FROM auth WHERE cif_nif = '12345678Z')
            """
        ),
        {"old": _OLD, "new": _NEW},
    )
