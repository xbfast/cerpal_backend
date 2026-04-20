"""Usuario y dirección de prueba para desarrollo (idempotente).

Credenciales (solo desarrollo): email test@cerpal.local, contraseña Test123!

Revision ID: 002_seed_test_user
Revises: 001_initial
Create Date: 2026-04-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_seed_test_user"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEST_EMAIL = "test@cerpal.local"


def upgrade() -> None:
    from app.security import hash_password

    bind = op.get_bind()
    password_hash = hash_password("Test123!")

    bind.execute(
        sa.text(
            """
            INSERT INTO auth (
                id,
                nombre_empresa,
                cif_nif,
                nombre_responsable,
                email,
                telefono,
                direccion,
                cp,
                ciudad,
                provincia,
                password_hash,
                validado,
                email_verificado,
                rol
            )
            VALUES (
                gen_random_uuid(),
                'Empresa de prueba Cerpal',
                '12345678Z',
                'Usuario Test',
                :email,
                '600000000',
                'Calle Prueba 1',
                '28001',
                'Madrid',
                'Madrid',
                :password_hash,
                true,
                true,
                'cliente'::user_role
            )
            ON CONFLICT (email) DO NOTHING
            """
        ),
        {"email": _TEST_EMAIL, "password_hash": password_hash},
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO direcciones (
                id,
                auth_id,
                name,
                direccion,
                cp,
                ciudad,
                provincia,
                telefono,
                persona_contacto,
                email,
                "default",
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                a.id,
                'Empresa de prueba Cerpal',
                'Calle Prueba 1',
                '28001',
                'Madrid',
                'Madrid',
                '600000000',
                'Usuario Test',
                :email,
                true,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM auth a
            WHERE lower(a.email) = lower(:email)
              AND NOT EXISTS (
                  SELECT 1 FROM direcciones d WHERE d.auth_id = a.id
              )
            """
        ),
        {"email": _TEST_EMAIL},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM direcciones
            WHERE auth_id IN (
                SELECT id FROM auth WHERE lower(email) = lower(:email)
            )
            """
        ),
        {"email": _TEST_EMAIL},
    )
    bind.execute(
        sa.text("DELETE FROM auth WHERE lower(email) = lower(:email)"),
        {"email": _TEST_EMAIL},
    )
