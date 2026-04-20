"""Esquema inicial: enum user_role y tablas auth, contacts, direcciones.

Revision ID: 001_initial
Revises:
Create Date: 2026-04-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role = postgresql.ENUM(
        "cliente",
        "comercial",
        "administrador",
        name="user_role",
        create_type=True,
    )
    user_role.create(op.get_bind(), checkfirst=True)

    user_role_col = postgresql.ENUM(
        "cliente",
        "comercial",
        "administrador",
        name="user_role",
        create_type=False,
    )

    op.create_table(
        "auth",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nombre_empresa", sa.String(length=255), nullable=False),
        sa.Column("cif_nif", sa.String(length=20), nullable=False),
        sa.Column("nombre_responsable", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("telefono", sa.String(length=20), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=False),
        sa.Column("cp", sa.String(length=10), nullable=False),
        sa.Column("ciudad", sa.String(length=100), nullable=False),
        sa.Column("provincia", sa.String(length=100), nullable=False),
        sa.Column("sector", sa.String(length=255), nullable=True),
        sa.Column("sitio_web", sa.String(length=500), nullable=True),
        sa.Column("email_facturas", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "validado",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "email_verificado",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "rol",
            user_role_col,
            server_default=sa.text("'cliente'::user_role"),
            nullable=False,
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
        sa.Column("password_reset_token_hash", sa.Text(), nullable=True),
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cif_nif"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_contacto", sa.String(length=255), nullable=True),
        sa.Column("cargo", sa.String(length=255), nullable=True),
        sa.Column("email_directo", sa.String(length=255), nullable=True),
        sa.Column("telefono", sa.String(length=40), nullable=True),
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
    )
    op.create_index(op.f("ix_contacts_auth_id"), "contacts", ["auth_id"], unique=False)

    op.create_table(
        "direcciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=False),
        sa.Column("cp", sa.String(length=10), nullable=False),
        sa.Column("ciudad", sa.String(length=100), nullable=False),
        sa.Column("provincia", sa.String(length=100), nullable=False),
        sa.Column("telefono", sa.String(length=30), nullable=True),
        sa.Column("persona_contacto", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column(
            "default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
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
        sa.ForeignKeyConstraint(["auth_id"], ["auth.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_direcciones_auth_id"), "direcciones", ["auth_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_direcciones_auth_id"), table_name="direcciones")
    op.drop_table("direcciones")
    op.drop_index(op.f("ix_contacts_auth_id"), table_name="contacts")
    op.drop_table("contacts")
    op.drop_table("auth")
    op.execute("DROP TYPE IF EXISTS user_role")
