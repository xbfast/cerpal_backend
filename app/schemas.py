from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.security import validate_password_policy
from app.spanish_tax_id import is_valid_spanish_tax_id, normalize_spanish_tax_id


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RecuperarContrasenaIn(BaseModel):
    email: EmailStr


class RestablecerContrasenaConTokenIn(BaseModel):
    token: str = Field(..., min_length=30)
    password: str = Field(..., min_length=8)

    @field_validator("token", mode="before")
    @classmethod
    def token_strip(cls, v: object) -> str:
        if v is None:
            raise ValueError("El token es obligatorio.")
        s = str(v).strip()
        if not s:
            raise ValueError("El token es obligatorio.")
        return s

    @field_validator("password")
    @classmethod
    def password_policy_y_bcrypt(cls, v: str) -> str:
        validate_password_policy(v)
        if len(v.encode("utf-8")) > 72:
            raise ValueError(
                "La contraseña no puede superar 72 bytes en UTF-8 (límite de bcrypt)."
            )
        return v


class RegistroCuentaIn(BaseModel):
    nombre_empresa: str = Field(..., max_length=255)
    cif_nif: str = Field(..., max_length=20)
    nombre_responsable: str = Field(..., max_length=255)
    email: EmailStr
    telefono: str = Field(..., max_length=20)
    direccion: str = Field(..., min_length=1)
    cp: str = Field(..., max_length=10)
    ciudad: str = Field(..., max_length=100)
    provincia: str = Field(..., max_length=100)
    password: str = Field(..., min_length=8)

    @field_validator("cif_nif", mode="before")
    @classmethod
    def cif_nif_valido_registro(cls, v: object) -> str:
        if v is None:
            raise ValueError("El CIF/NIF es obligatorio.")
        raw = str(v).strip()
        if not raw:
            raise ValueError("El CIF/NIF es obligatorio.")
        s = normalize_spanish_tax_id(raw)
        if not is_valid_spanish_tax_id(s):
            raise ValueError("Introduce un NIF, NIE o CIF español válido.")
        return s

    @field_validator("password")
    @classmethod
    def password_registro_policy_y_bcrypt(cls, v: str) -> str:
        validate_password_policy(v)
        if len(v.encode("utf-8")) > 72:
            raise ValueError("La contraseña no puede superar 72 bytes en UTF-8 (límite de bcrypt).")
        return v


class PerfilEmpresaFacturacionIn(BaseModel):
    """Empresa + facturación (no incluye contacto: responsable, email login, teléfono)."""

    nombre_empresa: str = Field(..., min_length=1, max_length=255)
    cif_nif: str = Field(..., min_length=1, max_length=20)
    sector: str | None = Field(None, max_length=255)
    sitio_web: str | None = Field(None, max_length=500)
    email_facturas: EmailStr | None = None
    direccion: str = Field(..., min_length=1)
    cp: str = Field(..., max_length=10)
    ciudad: str = Field(..., max_length=100)
    provincia: str = Field(..., max_length=100)

    @field_validator("cif_nif", mode="before")
    @classmethod
    def cif_nif_valido_perfil(cls, v: object) -> str:
        if v is None:
            raise ValueError("El CIF/NIF es obligatorio.")
        raw = str(v).strip()
        if not raw:
            raise ValueError("El CIF/NIF es obligatorio.")
        s = normalize_spanish_tax_id(raw)
        if not is_valid_spanish_tax_id(s):
            raise ValueError("Introduce un NIF, NIE o CIF español válido.")
        return s

    @field_validator("email_facturas", mode="before")
    @classmethod
    def email_facturas_vacio_a_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return v


class CambiarPasswordIn(BaseModel):
    password_actual: str = Field(..., min_length=1)
    password_nueva: str = Field(..., min_length=8)

    @field_validator("password_nueva")
    @classmethod
    def password_nueva_policy_y_bcrypt(cls, v: str) -> str:
        validate_password_policy(v)
        if len(v.encode("utf-8")) > 72:
            raise ValueError(
                "La contraseña no puede superar 72 bytes en UTF-8 (límite de bcrypt)."
            )
        return v


def contacto_tiene_identificador(
    persona: str | None, email: str | None, telefono: str | None
) -> bool:
    """Al menos uno de nombre, email o teléfono con valor no vacío."""
    if persona is not None and str(persona).strip():
        return True
    if email is not None and str(email).strip():
        return True
    if telefono is not None and str(telefono).strip():
        return True
    return False


class ContactCreate(BaseModel):
    persona_contacto: str | None = Field(None, max_length=255)
    cargo: str | None = Field(None, max_length=255)
    email_directo: EmailStr | None = None
    telefono: str | None = Field(None, max_length=40)

    @field_validator("persona_contacto", mode="before")
    @classmethod
    def persona_vacio_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None

    @field_validator("email_directo", mode="before")
    @classmethod
    def email_vacio_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return str(v).strip().lower()

    @field_validator("cargo", "telefono", mode="before")
    @classmethod
    def vacio_a_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None

    @model_validator(mode="after")
    def al_menos_un_medio(self) -> "ContactCreate":
        if not contacto_tiene_identificador(
            self.persona_contacto,
            str(self.email_directo) if self.email_directo is not None else None,
            self.telefono,
        ):
            raise ValueError(
                "Indica al menos uno: persona de contacto, email directo o teléfono."
            )
        return self


class ContactUpdate(BaseModel):
    persona_contacto: str | None = Field(None, max_length=255)
    cargo: str | None = Field(None, max_length=255)
    email_directo: EmailStr | None = None
    telefono: str | None = Field(None, max_length=40)

    @field_validator("persona_contacto", mode="before")
    @classmethod
    def persona_vacio_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None

    @field_validator("email_directo", mode="before")
    @classmethod
    def email_vacio_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return str(v).strip().lower()

    @field_validator("cargo", "telefono", mode="before")
    @classmethod
    def vacio_a_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auth_id: UUID
    persona_contacto: str | None
    cargo: str | None
    email_directo: str | None
    telefono: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DireccionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    direccion: str = Field(..., min_length=1)
    cp: str = Field(..., max_length=10)
    ciudad: str = Field(..., max_length=100)
    provincia: str = Field(..., max_length=100)
    telefono: str | None = Field(None, max_length=30)
    persona_contacto: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    is_default: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def email_vacio_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return str(v).strip().lower()

    @field_validator("telefono", "persona_contacto", mode="before")
    @classmethod
    def opcionales_strip(cls, v: object) -> object:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None


class DireccionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    direccion: str | None = Field(None, min_length=1)
    cp: str | None = Field(None, max_length=10)
    ciudad: str | None = Field(None, max_length=100)
    provincia: str | None = Field(None, max_length=100)
    telefono: str | None = Field(None, max_length=30)
    persona_contacto: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    is_default: bool | None = None

    @field_validator("email", mode="before")
    @classmethod
    def email_vacio_none_u(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return str(v).strip().lower()

    @field_validator("telefono", "persona_contacto", mode="before")
    @classmethod
    def opcionales_strip_u(cls, v: object) -> object:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None


class DireccionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auth_id: UUID
    name: str
    direccion: str
    cp: str
    ciudad: str
    provincia: str
    telefono: str | None
    persona_contacto: str | None
    email: str | None
    is_default: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RegistroCuentaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    nombre_empresa: str
    cif_nif: str
    nombre_responsable: str
    email: str
    telefono: str
    direccion: str
    cp: str
    ciudad: str
    provincia: str
    validado: bool
    email_verificado: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
