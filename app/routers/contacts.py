from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import AuthAccount, Contact
from app.schemas import (
    ContactCreate,
    ContactOut,
    ContactUpdate,
    contacto_tiene_identificador,
)

router = APIRouter(prefix="/api/auth/me/contacts", tags=["contacts"])

_MIGR_NULLABLE = (
    "Si la tabla `contacts` se creó antes con nombre o email obligatorios, ejecuta en "
    "PostgreSQL: `cerpal_backend/sql/alter_contacts_nullable_identificador.sql`."
)


def _integrity_error_detail(err: IntegrityError, *, actualizar: bool = False) -> str:
    """Mensaje legible ante NOT NULL, FK, etc."""
    verbo = "actualizar" if actualizar else "guardar"
    orig = getattr(err, "orig", None)
    if orig is None:
        return f"No se pudo {verbo} el contacto. {_MIGR_NULLABLE}"
    s = str(orig).lower()
    if "not null" in s or "null value" in s:
        return (
            "La base de datos no permite dejar vacíos algunos campos. "
            f"{_MIGR_NULLABLE}"
        )
    if "foreign key" in s:
        return "No se pudo vincular el contacto a la cuenta."
    return f"No se pudo {verbo} el contacto. {_MIGR_NULLABLE}"


def _get_owned_contact(
    db: Session, user_id: UUID, contact_id: UUID
) -> Contact | None:
    return db.scalar(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.auth_id == user_id,
        )
    )


@router.get("", response_model=list[ContactOut])
def listar_contactos(
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Contact]:
    return list(
        db.scalars(
            select(Contact)
            .where(Contact.auth_id == user.id)
            .order_by(Contact.created_at.desc())
        ).all()
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def crear_contacto(
    payload: ContactCreate,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Contact:
    mail = (
        str(payload.email_directo).strip().lower()
        if payload.email_directo is not None
        else None
    )
    row = Contact(
        auth_id=user.id,
        persona_contacto=payload.persona_contacto,
        cargo=payload.cargo,
        email_directo=mail,
        telefono=payload.telefono,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        detail = _integrity_error_detail(err)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datos del contacto no válidos o demasiado largos.",
        )
    saved = db.get(Contact, row.id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Contacto creado pero no se pudo leer.",
        )
    return saved


@router.patch("/{contact_id}", response_model=ContactOut)
def actualizar_contacto(
    contact_id: UUID,
    payload: ContactUpdate,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Contact:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay campos para actualizar.",
        )
    row = _get_owned_contact(db, user.id, contact_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contacto no encontrado.",
        )
    if "persona_contacto" in data:
        row.persona_contacto = data["persona_contacto"]
    if "cargo" in data:
        row.cargo = data["cargo"]
    if "email_directo" in data:
        row.email_directo = (
            str(data["email_directo"]).strip().lower()
            if data["email_directo"] is not None
            else None
        )
    if "telefono" in data:
        row.telefono = data["telefono"]
    if not contacto_tiene_identificador(
        row.persona_contacto, row.email_directo, row.telefono
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Debe quedar al menos uno: persona de contacto, email directo o teléfono."
            ),
        )
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_integrity_error_detail(err, actualizar=True),
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datos del contacto no válidos o demasiado largos.",
        )
    db.refresh(row)
    return row


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_contacto(
    contact_id: UUID,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    row = _get_owned_contact(db, user.id, contact_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contacto no encontrado.",
        )
    db.delete(row)
    try:
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo eliminar el contacto.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
