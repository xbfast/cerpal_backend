from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import AuthAccount, Direccion
from app.schemas import DireccionCreate, DireccionOut, DireccionUpdate

router = APIRouter(prefix="/api/auth/me/direcciones", tags=["direcciones"])


def _get_owned(
    db: Session, auth_id: UUID, direccion_id: UUID
) -> Direccion | None:
    return db.scalar(
        select(Direccion).where(
            Direccion.id == direccion_id,
            Direccion.auth_id == auth_id,
        )
    )


def _clear_all_defaults(db: Session, auth_id: UUID) -> None:
    db.execute(
        update(Direccion)
        .where(Direccion.auth_id == auth_id)
        .values(is_default=False)
    )


def _promote_first_as_default(db: Session, auth_id: UUID) -> None:
    first = db.scalar(
        select(Direccion)
        .where(Direccion.auth_id == auth_id)
        .order_by(Direccion.created_at.asc())
        .limit(1)
    )
    if first is not None:
        first.is_default = True


@router.get("", response_model=list[DireccionOut])
def listar_direcciones(
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Direccion]:
    rows = db.scalars(
        select(Direccion)
        .where(Direccion.auth_id == user.id)
        .order_by(Direccion.is_default.desc(), Direccion.created_at.desc())
    ).all()
    return list(rows)


@router.post("", response_model=DireccionOut, status_code=status.HTTP_201_CREATED)
def crear_direccion(
    payload: DireccionCreate,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Direccion:
    em = str(payload.email).strip().lower() if payload.email else None
    row = Direccion(
        auth_id=user.id,
        name=payload.name.strip(),
        direccion=payload.direccion.strip(),
        cp=payload.cp.strip(),
        ciudad=payload.ciudad.strip(),
        provincia=payload.provincia.strip(),
        telefono=payload.telefono,
        persona_contacto=payload.persona_contacto,
        email=em,
        is_default=False,
    )
    db.add(row)
    try:
        db.flush()
        if payload.is_default:
            _clear_all_defaults(db, user.id)
            row.is_default = True
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo guardar la dirección (revisa datos únicos o longitud).",
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo guardar la dirección.",
        )
    saved = db.get(Direccion, row.id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dirección creada pero no se pudo leer.",
        )
    return saved


@router.patch("/{direccion_id}", response_model=DireccionOut)
def actualizar_direccion(
    direccion_id: UUID,
    payload: DireccionUpdate,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Direccion:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay campos para actualizar.",
        )
    row = _get_owned(db, user.id, direccion_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dirección no encontrada.",
        )
    if "name" in data:
        row.name = str(data["name"]).strip()
    if "direccion" in data:
        row.direccion = str(data["direccion"]).strip()
    if "cp" in data:
        row.cp = str(data["cp"]).strip()
    if "ciudad" in data:
        row.ciudad = str(data["ciudad"]).strip()
    if "provincia" in data:
        row.provincia = str(data["provincia"]).strip()
    if "telefono" in data:
        row.telefono = data["telefono"]
    if "persona_contacto" in data:
        row.persona_contacto = data["persona_contacto"]
    if "email" in data:
        row.email = data["email"]
    want_default = data.get("is_default")
    try:
        if want_default is True:
            _clear_all_defaults(db, user.id)
            row.is_default = True
        elif want_default is False:
            row.is_default = False
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo actualizar la dirección.",
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo actualizar la dirección.",
        )
    db.refresh(row)
    return row


@router.delete("/{direccion_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_direccion(
    direccion_id: UUID,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    row = _get_owned(db, user.id, direccion_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dirección no encontrada.",
        )
    total = (
        db.scalar(
            select(func.count())
            .select_from(Direccion)
            .where(Direccion.auth_id == user.id)
        )
        or 0
    )
    if total <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes mantener al menos una dirección de envío.",
        )
    was_default = row.is_default
    db.delete(row)
    try:
        db.flush()
        if was_default:
            _promote_first_as_default(db, user.id)
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo eliminar la dirección.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
