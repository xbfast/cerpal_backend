import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import AuthAccount, Direccion
from app.password_reset import (
    generate_password_reset_secret,
    hash_password_reset_token,
    send_password_reset_email,
)
from app.schemas import (
    CambiarPasswordIn,
    LoginIn,
    PerfilEmpresaFacturacionIn,
    RecuperarContrasenaIn,
    RegistroCuentaIn,
    RestablecerContrasenaConTokenIn,
)
from app.security import hash_password, verify_password
from app.tokens import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _respuesta_registro(saved: AuthAccount) -> dict:
    """Solo campos públicos, tipos JSON-safe (evita fallos al serializar la respuesta)."""
    return {
        "id": str(saved.id),
        "nombre_empresa": saved.nombre_empresa,
        "cif_nif": saved.cif_nif,
        "nombre_responsable": saved.nombre_responsable,
        "email": saved.email,
        "telefono": saved.telefono,
        "direccion": saved.direccion,
        "cp": saved.cp,
        "ciudad": saved.ciudad,
        "provincia": saved.provincia,
        "sector": saved.sector,
        "sitio_web": saved.sitio_web,
        "email_facturas": saved.email_facturas,
        "validado": bool(saved.validado),
        "email_verificado": bool(saved.email_verificado),
        "rol": str(saved.rol).strip().lower() if saved.rol is not None else "cliente",
        "created_at": saved.created_at.isoformat() if saved.created_at else None,
        "updated_at": saved.updated_at.isoformat() if saved.updated_at else None,
    }


def _conflicto_registro(db: Session, cif_nif: str, email: str) -> str | None:
    """Devuelve mensaje de error si CIF o email ya existen; si no, None."""
    partes: list[str] = []
    cif = cif_nif.strip().upper()
    mail = email.strip().lower()
    if db.scalar(
        select(AuthAccount.id).where(func.upper(AuthAccount.cif_nif) == cif)
    ):
        partes.append("Este CIF/NIF ya está registrado.")
    if db.scalar(
        select(AuthAccount.id).where(func.lower(AuthAccount.email) == mail)
    ):
        partes.append("Este email ya está registrado.")
    if not partes:
        return None
    return " ".join(partes)


@router.get("/me")
def perfil_actual(user: AuthAccount = Depends(get_current_user)) -> dict:
    """Perfil público del usuario autenticado (p. ej. para refrescar `rol` tras cambios en BD)."""
    return _respuesta_registro(user)


@router.patch("/me/perfil-empresa")
def actualizar_perfil_empresa_y_facturacion(
    payload: PerfilEmpresaFacturacionIn,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Actualiza empresa y dirección de facturación.
    No modifica datos de contacto (nombre_responsable, email, teléfono).
    """
    cif = payload.cif_nif.strip().upper()
    if cif != user.cif_nif.upper():
        ocupado = db.scalar(
            select(AuthAccount.id).where(
                func.upper(AuthAccount.cif_nif) == cif,
                AuthAccount.id != user.id,
            )
        )
        if ocupado is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este CIF/NIF ya está registrado en otra cuenta.",
            )

    user.nombre_empresa = payload.nombre_empresa.strip()
    user.cif_nif = cif
    user.direccion = payload.direccion.strip()
    user.cp = payload.cp.strip()
    user.ciudad = payload.ciudad.strip()
    user.provincia = payload.provincia.strip()
    sec = payload.sector.strip() if payload.sector else ""
    user.sector = sec if sec else None
    sw = payload.sitio_web.strip() if payload.sitio_web else ""
    user.sitio_web = sw if sw else None
    user.email_facturas = (
        str(payload.email_facturas).strip().lower()
        if payload.email_facturas
        else None
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo guardar. Revisa CIF/NIF y datos únicos.",
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo guardar el perfil. Revisa formato y longitud de los campos.",
        )

    saved = db.get(AuthAccount, user.id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cambios guardados pero no se pudo leer el perfil.",
        )
    return _respuesta_registro(saved)


@router.post("/me/password")
def cambiar_password(
    payload: CambiarPasswordIn,
    user: AuthAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Actualiza la contraseña tras comprobar la actual."""
    if not verify_password(payload.password_actual, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual no es correcta.",
        )
    if verify_password(payload.password_nueva, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña debe ser distinta de la actual.",
        )
    user.password_hash = hash_password(payload.password_nueva)
    try:
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo actualizar la contraseña. Inténtalo de nuevo.",
        )
    return {"ok": True}


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/forgot-password")
def solicitar_recuperacion_contrasena(
    payload: RecuperarContrasenaIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """
    Respuesta uniforme (no revela si el email existe).
    Si hay cuenta, guarda token y encola envío SMTP con enlace al frontend.
    """
    email = str(payload.email).strip().lower()
    user = db.scalar(
        select(AuthAccount).where(func.lower(AuthAccount.email) == email)
    )
    if user is not None:
        plain, token_hash, expires = generate_password_reset_secret()
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = expires
        try:
            db.commit()
        except DBAPIError:
            db.rollback()
            logger.exception("No se pudo guardar el token de recuperación de contraseña.")
        else:
            display = (user.nombre_responsable or user.nombre_empresa or "").strip()
            background_tasks.add_task(
                send_password_reset_email, user.email, display, plain
            )
    return {"ok": True}


@router.post("/reset-password")
def restablecer_contrasena_con_token(
    payload: RestablecerContrasenaConTokenIn,
    db: Session = Depends(get_db),
) -> dict:
    """Consume un token válido y fija la nueva contraseña."""
    token_hash = hash_password_reset_token(payload.token)
    now = _utc_naive_now()
    user = db.scalar(
        select(AuthAccount).where(
            AuthAccount.password_reset_token_hash == token_hash,
            AuthAccount.password_reset_expires_at.is_not(None),
            AuthAccount.password_reset_expires_at > now,
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace no es válido o ha caducado. Solicita uno nuevo desde el acceso.",
        )
    if verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña debe ser distinta de la anterior.",
        )
    user.password_hash = hash_password(payload.password)
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    try:
        db.commit()
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo actualizar la contraseña. Inténtalo de nuevo.",
        )
    return {"ok": True}


@router.post("/login")
def iniciar_sesion(payload: LoginIn, db: Session = Depends(get_db)) -> dict:
    email = str(payload.email).strip().lower()
    user = db.scalar(
        select(AuthAccount).where(func.lower(AuthAccount.email) == email)
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos.",
        )
    if not bool(user.validado):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Tu cuenta aún no está validada. Cuando el equipo revise tu solicitud "
                "(24-48h hábiles) podrás iniciar sesión. Si necesitas ayuda, contacta con nosotros."
            ),
        )
    token = create_access_token(sub=str(user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _respuesta_registro(user),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def registrar_cuenta(payload: RegistroCuentaIn, db: Session = Depends(get_db)) -> dict:
    cif_nif = payload.cif_nif.strip().upper()
    email = str(payload.email).strip().lower()

    msg = _conflicto_registro(db, cif_nif, email)
    if msg:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)

    cuenta = AuthAccount(
        nombre_empresa=payload.nombre_empresa.strip(),
        cif_nif=cif_nif,
        nombre_responsable=payload.nombre_responsable.strip(),
        email=email,
        telefono=payload.telefono.strip(),
        direccion=payload.direccion.strip(),
        cp=payload.cp.strip(),
        ciudad=payload.ciudad.strip(),
        provincia=payload.provincia.strip(),
        password_hash=hash_password(payload.password),
        rol="cliente",
    )
    db.add(cuenta)
    db.flush()
    db.add(
        Direccion(
            auth_id=cuenta.id,
            name=payload.nombre_empresa.strip()[:255],
            direccion=payload.direccion.strip(),
            cp=payload.cp.strip(),
            ciudad=payload.ciudad.strip(),
            provincia=payload.provincia.strip(),
            telefono=payload.telefono.strip(),
            persona_contacto=payload.nombre_responsable.strip(),
            email=email,
            is_default=True,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email o el CIF/NIF ya están registrados.",
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo guardar el registro. Revisa formato y longitud de los campos.",
        )

    # Tras commit, recargar por PK (más fiable que refresh() en algunos despliegues)
    saved = db.get(AuthAccount, cuenta.id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registro guardado pero no se pudo leer de la base de datos.",
        )
    return _respuesta_registro(saved)
