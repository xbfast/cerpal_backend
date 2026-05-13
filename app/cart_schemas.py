"""Esquemas del carrito (API snake_case, alineado con `useCartStore` del frontend)."""

from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CartLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID
    catalog: Literal["impresion", "rotulacion"]
    slug: str = Field(..., min_length=1, max_length=512)
    title: str = Field(..., min_length=1, max_length=512)
    image: str = Field(..., max_length=2048)
    product_ref: str = Field(..., min_length=1, max_length=128)
    kind: Literal["unit", "m2"]
    quantity: int = Field(..., ge=1, le=99_999)
    price_per_unit: float = Field(..., ge=0, le=9_999_999.99)
    unit_label: str | None = Field(None, max_length=512)
    options_summary: str | None = Field(None, max_length=1024)
    surface_m2: float | None = Field(None, ge=0, le=1_000_000)
    provider_ref: str | None = Field(None, max_length=128)
    color_name: str | None = Field(None, max_length=512)
    detail_line: str | None = Field(None, max_length=512)
    color_ref: str | None = Field(None, max_length=128)
    roll_width_key: str | None = Field(None, max_length=64)
    metros_lineales: float | None = Field(None, ge=0, le=1_000_000)

    @field_validator(
        "unit_label",
        "options_summary",
        "provider_ref",
        "color_name",
        "detail_line",
        "color_ref",
        "roll_width_key",
        mode="before",
    )
    @classmethod
    def opcional_vacio_a_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        if isinstance(v, str):
            return v.strip()
        return v


class CartReplaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[CartLineItem] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def ids_unicos(self) -> Self:
        ids = [ln.id for ln in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay líneas con el mismo id.")
        return self


class CartOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[dict[str, Any]]
