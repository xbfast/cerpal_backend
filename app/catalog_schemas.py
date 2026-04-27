from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CatalogVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    default_code: str
    name: str | None = None
    list_price: float = 0
    integrable: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)
    # Primer código hex útil del valor de atributo tipo color (si existe en BD).
    color_hex: str | None = None


class CatalogListItemOut(BaseModel):
    """Forma alineada con `CatalogProductCard` + mocks."""

    catalog: Literal["impresion", "rotulacion"]
    id: str
    slug: str
    title: str
    description: str
    price: str
    image: str
    badge: str
    reference: str
    swatchKeys: list[str] = Field(default_factory=list)
    extraColors: int = 0


class CatalogListPageOut(BaseModel):
    """Listado paginado de plantillas para grid + scroll infinito."""

    items: list[CatalogListItemOut]
    total: int
    offset: int
    limit: int


class CatalogProductDetailOut(CatalogListItemOut):
    descriptionDetail: str | None = None
    characteristics: list[str] = Field(default_factory=list)
    fichaTecnica: list[str] = Field(default_factory=list)
    cartaColores: str | None = None
    gallery: list[str] | None = None
    variants: list[CatalogVariantOut] = Field(default_factory=list)
