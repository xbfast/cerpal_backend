"""Catálogo público (plantillas / variantes) leído de PostgreSQL.

Esquema alineado con `migracion_catalogo.py` / Odoo-like:
- product_template, product_product (template_id)
- product_variant_attribute_value (product_id, attribute_line_id, attribute_value_id)
- product_attribute.attr_type ('select' | 'color'), product_attribute_value.color_html

«Rotulación» = plantillas en categoría raíz 1 o subcategorías (parent_id = 1).
«Impresión» = el resto (incl. sin categoría).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.catalog_schemas import (
    CatalogListItemOut,
    CatalogListPageOut,
    CatalogProductDetailOut,
    CatalogVariantOut,
)
from app.catalog_utils import (
    PLACEHOLDER_PRODUCT_IMAGE,
    format_price_eur,
    slug_from_default_code,
    swatch_keys_from_color_names,
    truncate_text,
)
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

# Árbol comercial «Rotulación» en product_category (seed: id=1 + hijas con parent_id=1).
_ROTULACION_SQL = """
pt.category_id IN (
    SELECT pc.id FROM product_category pc
    WHERE pc.id = 1 OR pc.parent_id = 1
)
"""

_IMPRESION_SQL = f"""
(
    pt.category_id IS NULL
    OR NOT ({_ROTULACION_SQL.strip()})
)
"""

_COUNT_LIST_SQL = text(f"""
SELECT COUNT(*)::int AS n
FROM product_template pt
WHERE COALESCE(pt.active, TRUE)
  AND (
    (NOT :for_rotulacion AND {_IMPRESION_SQL})
    OR (:for_rotulacion AND {_ROTULACION_SQL})
  )
""")

_COLOR_PREDICATE = """
(
    pa.attr_type = 'color'
    OR lower(pa.name) LIKE '%color%'
    OR lower(pa.name) LIKE '%tinta%'
    OR lower(pa.name) LIKE '%colore%'
)
"""

_COLOR_SQL = text(f"""
SELECT pt.id AS tmpl_id, array_agg(DISTINCT pav.name ORDER BY pav.name) AS color_names
FROM product_template pt
JOIN product_product pp ON pp.template_id = pt.id
JOIN product_variant_attribute_value pvav ON pvav.product_id = pp.id
JOIN product_template_attribute_line ptal ON ptal.id = pvav.attribute_line_id
JOIN product_attribute pa ON pa.id = ptal.attribute_id
JOIN product_attribute_value pav ON pav.id = pvav.attribute_value_id
WHERE pt.id IN :ids
  AND {_COLOR_PREDICATE}
GROUP BY pt.id
""").bindparams(bindparam("ids", expanding=True))

_LIST_WITH_COLORS_SQL = text(f"""
SELECT
    pt.id,
    pt.default_code,
    pt.name,
    (
        SELECT coalesce(
            array_agg(sub.name ORDER BY sub.name),
            ARRAY[]::varchar[]
        )
        FROM (
            SELECT DISTINCT pav.name
            FROM product_product pp
            JOIN product_variant_attribute_value pvav ON pvav.product_id = pp.id
            JOIN product_template_attribute_line ptal ON ptal.id = pvav.attribute_line_id
            JOIN product_attribute pa ON pa.id = ptal.attribute_id
            JOIN product_attribute_value pav ON pav.id = pvav.attribute_value_id
            WHERE pp.template_id = pt.id
              AND {_COLOR_PREDICATE}
        ) AS sub(name)
    ) AS color_names
FROM product_template pt
WHERE COALESCE(pt.active, TRUE)
  AND (
    (NOT :for_rotulacion AND {_IMPRESION_SQL})
    OR (:for_rotulacion AND {_ROTULACION_SQL})
  )
ORDER BY pt.default_code
LIMIT :limit OFFSET :offset
""")

_TEMPLATE_BY_SLUG_SQL = text(f"""
SELECT pt.id, pt.default_code, pt.name, pt.active
FROM product_template pt
WHERE COALESCE(pt.active, TRUE)
  AND lower(regexp_replace(trim(pt.default_code), '[^a-zA-Z0-9]+', '-', 'g')) = :slug
  AND (
    (NOT :for_rotulacion AND {_IMPRESION_SQL})
    OR (:for_rotulacion AND {_ROTULACION_SQL})
  )
LIMIT 1
""")

_VARIANT_ROWS_SQL = text("""
SELECT
    pp.id AS variant_id,
    pp.default_code AS variant_code,
    pp.name AS variant_name,
    pa.name AS attribute_name,
    pa.attr_type AS attr_display_type,
    pav.name AS attribute_value,
    pav.color_html AS value_html_color
FROM product_product pp
JOIN product_template pt ON pt.id = pp.template_id
LEFT JOIN product_variant_attribute_value pvav ON pvav.product_id = pp.id
LEFT JOIN product_template_attribute_line ptal ON ptal.id = pvav.attribute_line_id
LEFT JOIN product_attribute pa ON pa.id = ptal.attribute_id
LEFT JOIN product_attribute_value pav ON pav.id = pvav.attribute_value_id
WHERE pt.id = :tmpl_id
  AND COALESCE(pp.active, TRUE)
ORDER BY pp.default_code, pa.name
""")


def _badge_for_catalog(catalog: str) -> str:
    return "Impresión" if catalog == "impresion" else "Rotulación"


def _validate_catalog(catalog: str) -> str:
    if catalog not in ("impresion", "rotulacion"):
        raise HTTPException(status_code=404, detail="Catálogo no válido")
    return catalog


def _row_to_list_item(
    row: Mapping[str, object],
    catalog: str,
    color_names: list[str] | None,
) -> CatalogListItemOut:
    default_code = str(row["default_code"])
    slug = slug_from_default_code(default_code)
    title = str(row["name"] or default_code)
    keys, extra = swatch_keys_from_color_names(color_names)
    return CatalogListItemOut(
        catalog=catalog,  # type: ignore[arg-type]
        id=f"tmpl-{row['id']}",
        slug=slug,
        title=title,
        description=truncate_text(title, 220),
        price=format_price_eur(row.get("list_price")),  # type: ignore[arg-type]
        image=PLACEHOLDER_PRODUCT_IMAGE,
        badge=_badge_for_catalog(catalog),
        reference=default_code,
        swatchKeys=keys,
        extraColors=extra,
    )


def _normalize_pg_text_array(val: object) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x is not None]
    return [str(val)]


def _fetch_color_map(db: Session, tmpl_ids: Sequence[int]) -> dict[int, list[str]]:
    if not tmpl_ids:
        return {}
    try:
        res = db.execute(_COLOR_SQL, {"ids": list(tmpl_ids)}).mappings().all()
    except ProgrammingError as e:
        logger.warning("Consulta de colores omitida: %s", e)
        return {}
    out: dict[int, list[str]] = {}
    for r in res:
        tid = int(r["tmpl_id"])
        names = r.get("color_names")
        if isinstance(names, list):
            out[tid] = [str(x) for x in names if x is not None]
        elif names is not None:
            out[tid] = [str(names)]
    return out


@router.get("/featured", response_model=list[CatalogListItemOut])
def catalog_featured(
    limit: int = Query(8, ge=1, le=32),
    db: Session = Depends(get_db),
):
    """Mezcla breve impresión + rotulación para home (si hay datos en ambos)."""
    half = max(1, limit // 2)
    rest = limit - half
    _feat_sql = text(f"""
SELECT pt.id, pt.default_code, pt.name
FROM product_template pt
WHERE COALESCE(pt.active, TRUE)
  AND (
    (NOT :for_rotulacion AND {_IMPRESION_SQL})
    OR (:for_rotulacion AND {_ROTULACION_SQL})
  )
ORDER BY pt.id
LIMIT :lim
""")
    try:
        rows_imp = db.execute(
            _feat_sql,
            {"for_rotulacion": False, "lim": half},
        ).mappings().all()
        rows_rot = db.execute(
            _feat_sql,
            {"for_rotulacion": True, "lim": rest},
        ).mappings().all()
    except ProgrammingError as e:
        logger.exception("Catálogo featured: error de consulta %s", e)
        raise HTTPException(
            status_code=503,
            detail="Catálogo no disponible (error al leer la base de datos).",
        ) from e

    combined: list[tuple[str, Mapping[str, object]]] = [
        *(("impresion", r) for r in rows_imp),
        *(("rotulacion", r) for r in rows_rot),
    ]
    ids = [int(r["id"]) for _, r in combined]
    colors = _fetch_color_map(db, ids)
    return [
        _row_to_list_item(r, cat, colors.get(int(r["id"])))
        for cat, r in combined[:limit]
    ]


@router.get("/{catalog}", response_model=CatalogListPageOut)
def list_catalog(
    catalog: str,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Listado por catálogo (solo impresión o solo rotulación), paginado."""
    catalog = _validate_catalog(catalog)
    fr = catalog == "rotulacion"
    params = {"for_rotulacion": fr, "limit": limit, "offset": offset}
    try:
        total_row = db.execute(_COUNT_LIST_SQL, {"for_rotulacion": fr}).mappings().first()
        total = int(total_row["n"]) if total_row is not None else 0
        rows = db.execute(_LIST_WITH_COLORS_SQL, params).mappings().all()
    except ProgrammingError as e:
        logger.exception("Listado catálogo: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Catálogo no disponible (error al leer la base de datos).",
        ) from e

    items = [
        _row_to_list_item(
            r,
            catalog,
            _normalize_pg_text_array(r.get("color_names")),
        )
        for r in rows
    ]
    return CatalogListPageOut(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


def _build_characteristics_from_variants(
    variant_attrs: Iterable[dict[str, str]],
    *,
    max_lines: int = 16,
) -> list[str]:
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for attrs in variant_attrs:
        for k, v in sorted(attrs.items(), key=lambda kv: kv[0].lower()):
            key = (k, v)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{k}: {v}")
            if len(lines) >= max_lines:
                return lines
    return lines


@router.get("/{catalog}/{slug}", response_model=CatalogProductDetailOut)
def get_catalog_product(catalog: str, slug: str, db: Session = Depends(get_db)):
    catalog = _validate_catalog(catalog)
    slug_norm = slug.strip().lower()
    if not slug_norm:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    try:
        row = db.execute(
            _TEMPLATE_BY_SLUG_SQL,
            {
                "slug": slug_norm,
                "for_rotulacion": catalog == "rotulacion",
            },
        ).mappings().first()
    except ProgrammingError as e:
        logger.exception("Detalle catálogo: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Catálogo no disponible (error al leer la base de datos).",
        ) from e

    if row is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    tmpl_id = int(row["id"])
    default_code = str(row["default_code"])
    title = str(row["name"] or default_code)
    color_names = _fetch_color_map(db, [tmpl_id]).get(tmpl_id)
    keys, extra = swatch_keys_from_color_names(color_names)

    vrows = db.execute(_VARIANT_ROWS_SQL, {"tmpl_id": tmpl_id}).mappings().all()
    by_vid: dict[int, dict[str, object]] = {}
    attrs_by_vid: dict[int, dict[str, str]] = defaultdict(dict)
    hex_by_vid: dict[int, str | None] = {}
    is_rotulacion_catalog = catalog == "rotulacion"

    for vr in vrows:
        vid = int(vr["variant_id"])
        if vid not in by_vid:
            by_vid[vid] = {
                "id": vid,
                "default_code": str(vr["variant_code"]),
                "name": vr["variant_name"],
                "list_price": 0.0,
                "integrable": is_rotulacion_catalog,
            }
        an = vr.get("attribute_name")
        av = vr.get("attribute_value")
        if an and av:
            attrs_by_vid[vid][str(an)] = str(av)
        raw_hex = vr.get("value_html_color")
        disp = (vr.get("attr_display_type") or "").lower()
        an_s = str(an).lower() if an else ""
        is_colorish = (
            disp == "color"
            or "color" in an_s
            or "tinta" in an_s
            or "colore" in an_s
        )
        if raw_hex and is_colorish:
            hx = str(raw_hex).strip()
            low = hx.lower()
            if low not in ("#ffffff", "#fff", ""):
                if vid not in hex_by_vid or hex_by_vid[vid] is None:
                    hex_by_vid[vid] = hx

    variants: list[CatalogVariantOut] = []
    for vid, base in sorted(by_vid.items(), key=lambda x: x[1]["default_code"]):  # type: ignore[index]
        variants.append(
            CatalogVariantOut(
                id=int(base["id"]),  # type: ignore[arg-type]
                default_code=str(base["default_code"]),
                name=base["name"] if base["name"] is None else str(base["name"]),
                list_price=float(base["list_price"] or 0),
                integrable=bool(base["integrable"]),
                attributes=dict(attrs_by_vid[vid]),
                color_hex=hex_by_vid.get(vid),
            )
        )

    characteristics = _build_characteristics_from_variants(v.attributes for v in variants)

    num_v = len(variants)
    desc_detail = (
        f"{title}\n\n"
        f"Referencias en catálogo: {num_v} variante(s). "
        f"Elige opciones en el configurador; los importes de muestra siguen siendo orientativos hasta conectar precios por variante."
    )

    base_item = _row_to_list_item(row, catalog, color_names)
    return CatalogProductDetailOut(
        **base_item.model_dump(),
        descriptionDetail=desc_detail,
        characteristics=characteristics,
        fichaTecnica=[],
        cartaColores=(
            "Colores mostrados son orientativos (datos de catálogo). "
            "Confirma tono con muestra física o referencia comercial."
            if catalog == "rotulacion"
            else None
        ),
        gallery=None,
        variants=variants,
    )
