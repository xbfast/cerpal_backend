"""Catálogo público (plantillas / variantes) leído de PostgreSQL.

Esquema alineado con `migracion_catalogo.py` / Odoo-like:
- product_template, product_product (template_id)
- product_variant_attribute_value (product_id, attribute_line_id, attribute_value_id)
- product_attribute.attr_type ('select' | 'color'), product_attribute_value.color_html

«Rotulación» = plantillas en categoría raíz 1 o subcategorías (vía product_template_category).
«Impresión» = plantillas en categoría raíz 2 o subcategorías.
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.catalog_schemas import (
    AttributeValueSpecOut,
    CatalogListItemOut,
    CatalogListPageOut,
    CatalogProductDetailOut,
    CatalogSearchResultOut,
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


def _category_branch_sql(root_id: int) -> str:
    root_code = str(root_id)
    return f"""
(
    EXISTS (
        SELECT 1
        FROM product_template_category ptc
        JOIN product_category pc ON pc.id = ptc.category_id
        WHERE ptc.template_id = pt.id
          AND (
            pc.category_code = '{root_code}'
            OR pc.category_code LIKE '{root_code}.%'
          )
    )
)
"""


# Se publican todos los productos salvo las ramas descartadas:
# 3 (Tintas), 4 (Maquinaria), 5 (Sublimación/Textil) y 6 (Accesorios).
_EXCLUDED_CATALOG_SQL = f"""
(
    {_category_branch_sql(3).strip()}
    OR {_category_branch_sql(4).strip()}
    OR {_category_branch_sql(5).strip()}
    OR {_category_branch_sql(6).strip()}
)
"""

_PRINT_MATERIAL_KIND_SQL = """
(
    EXISTS (
        SELECT 1
        FROM product_template_attribute_line ptal_imp
        JOIN product_attribute pa_imp ON pa_imp.id = ptal_imp.attribute_id
        WHERE ptal_imp.template_id = pt.id
          AND (
            lower(pa_imp.name) LIKE '%ancho%bobina%'
            OR lower(pa_imp.name) LIKE '%tipo de vinilo%'
            OR lower(pa_imp.name) LIKE '%tipo de laminado%'
            OR lower(pa_imp.name) LIKE '%tipo de adhesivo%'
            OR lower(pa_imp.name) LIKE '%aplicación%'
            OR lower(pa_imp.name) LIKE '%aplicacion%'
            OR lower(pa_imp.name) LIKE '%duración%'
            OR lower(pa_imp.name) LIKE '%duracion%'
            OR lower(pa_imp.name) LIKE '%acabado%'
          )
    )
)
"""

_ROTULACION_KIND_SQL = f"""
(
    {_category_branch_sql(1).strip()}
    OR EXISTS (
        SELECT 1
        FROM product_template_attribute_line ptal_rot
        JOIN product_attribute pa_rot ON pa_rot.id = ptal_rot.attribute_id
        WHERE ptal_rot.template_id = pt.id
          AND lower(pa_rot.name) LIKE '%rotulación%'
    )
)
"""

_IMPRESION_KIND_SQL = f"""
(
    {_category_branch_sql(2).strip()}
    OR {_PRINT_MATERIAL_KIND_SQL.strip()}
)
"""

_PUBLIC_CATALOG_SQL = f"""
(
    NOT ({_EXCLUDED_CATALOG_SQL.strip()})
    AND (
        {_ROTULACION_KIND_SQL.strip()}
        OR {_IMPRESION_KIND_SQL.strip()}
    )
)
"""

_ROTULACION_SQL = f"""
(
    {_PUBLIC_CATALOG_SQL.strip()}
    AND {_ROTULACION_KIND_SQL.strip()}
)
"""

_IMPRESION_SQL = f"""
(
    {_PUBLIC_CATALOG_SQL.strip()}
    AND NOT ({_ROTULACION_KIND_SQL.strip()})
    AND {_IMPRESION_KIND_SQL.strip()}
)
"""

# Catálogo público: solo plantillas y variantes con active = TRUE.
_TEMPLATE_HAS_ACTIVE_VARIANT_SQL = """
EXISTS (
    SELECT 1
    FROM product_product pp_chk
    WHERE pp_chk.template_id = pt.id
      AND pp_chk.active IS TRUE
)
"""

_COUNT_LIST_SQL = text(f"""
SELECT COUNT(*)::int AS n
FROM product_template pt
WHERE pt.active IS TRUE
  AND pt.default_code ~ '^A'
  AND {_TEMPLATE_HAS_ACTIVE_VARIANT_SQL.strip()}
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
JOIN product_product pp ON pp.template_id = pt.id AND pp.active IS TRUE
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
    price_info.list_price,
    price_info.image_url,
    price_info.description_short,
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
              AND pp.active IS TRUE
              AND {_COLOR_PREDICATE}
        ) AS sub(name)
    ) AS color_names
FROM product_template pt
LEFT JOIN LATERAL (
    SELECT pp.list_price, pp.image_url, pp.gallery_jsonb, pp.description_short
    FROM product_product pp
    WHERE pp.template_id = pt.id
      AND pp.active IS TRUE
    ORDER BY
        (CASE WHEN pp.description_short IS NOT NULL AND btrim(pp.description_short) <> '' THEN 1 ELSE 0 END) DESC,
        pp.list_price NULLS LAST,
        pp.default_code
    LIMIT 1
) price_info ON TRUE
WHERE pt.active IS TRUE
  AND pt.default_code ~ '^A'
  AND {_TEMPLATE_HAS_ACTIVE_VARIANT_SQL.strip()}
  AND (
    (NOT :for_rotulacion AND {_IMPRESION_SQL})
    OR (:for_rotulacion AND {_ROTULACION_SQL})
  )
ORDER BY pt.default_code
LIMIT :limit OFFSET :offset
""")

_TEMPLATE_BY_SLUG_SQL = text(f"""
SELECT
    pt.id,
    pt.default_code,
    pt.name,
    pt.active,
    price_info.list_price,
    price_info.image_url,
    price_info.gallery_jsonb,
    price_info.description_short,
    price_info.description_long
FROM product_template pt
LEFT JOIN LATERAL (
    SELECT
        pp.list_price,
        pp.image_url,
        pp.gallery_jsonb,
        pp.description_short,
        pp.description_long
    FROM product_product pp
    WHERE pp.template_id = pt.id
      AND pp.active IS TRUE
    ORDER BY
        (CASE WHEN pp.description_short IS NOT NULL AND btrim(pp.description_short) <> '' THEN 1 ELSE 0 END
         + CASE WHEN pp.description_long IS NOT NULL AND btrim(pp.description_long) <> '' THEN 1 ELSE 0 END) DESC,
        pp.list_price NULLS LAST,
        pp.default_code
    LIMIT 1
) price_info ON TRUE
WHERE pt.active IS TRUE
  AND pt.default_code ~ '^A'
  AND {_TEMPLATE_HAS_ACTIVE_VARIANT_SQL.strip()}
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
    pp.list_price AS variant_list_price,
    pp.image_url AS variant_image_url,
    pp.gallery_jsonb AS variant_gallery_jsonb,
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
  AND pp.active IS TRUE
ORDER BY pp.default_code, pa.name
""")

_TEMPLATE_ATTR_TYPES_SQL = text("""
SELECT DISTINCT pa.name AS attr_name, pa.attr_type
FROM product_template_attribute_line ptal
JOIN product_attribute pa ON pa.id = ptal.attribute_id
WHERE ptal.template_id = :tmpl_id
ORDER BY pa.name
""")

_VALUE_SPECS_SQL = text("""
SELECT DISTINCT ON (pa.name, pav.name)
    pa.name AS attr_name,
    pav.name AS val_name,
    pav.color_html,
    pav.pantone,
    pav.cmyk,
    pav.ral
FROM product_product pp
JOIN product_variant_attribute_value pvav ON pvav.product_id = pp.id
JOIN product_template_attribute_line ptal ON ptal.id = pvav.attribute_line_id
JOIN product_attribute pa ON pa.id = ptal.attribute_id
JOIN product_attribute_value pav ON pav.id = pvav.attribute_value_id
WHERE pp.template_id = :tmpl_id
  AND pp.active IS TRUE
ORDER BY pa.name, pav.name, pp.id
""")

_SEARCH_SQL = text(f"""
SELECT
    pt.id AS template_id,
    pt.default_code AS template_code,
    pt.name AS template_name,
    pp.id AS variant_id,
    pp.default_code AS variant_code,
    pp.name AS variant_name,
    pp.list_price AS variant_list_price,
    pp.image_url AS variant_image_url,
    pp.gallery_jsonb AS variant_gallery_jsonb,
    attrs.properties AS properties,
    CASE WHEN {_ROTULACION_SQL} THEN 'rotulacion' ELSE 'impresion' END AS catalog
FROM product_product pp
JOIN product_template pt ON pt.id = pp.template_id
LEFT JOIN LATERAL (
    SELECT COALESCE(jsonb_object_agg(pa.name, pav.name), '{{}}'::jsonb) AS properties
    FROM product_variant_attribute_value pvav
    JOIN product_template_attribute_line ptal ON ptal.id = pvav.attribute_line_id
    JOIN product_attribute pa ON pa.id = ptal.attribute_id
    JOIN product_attribute_value pav ON pav.id = pvav.attribute_value_id
    WHERE pvav.product_id = pp.id
) attrs ON TRUE
WHERE pt.active IS TRUE
  AND pp.active IS TRUE
  AND pt.default_code ~ '^A'
  AND {_PUBLIC_CATALOG_SQL}
  AND (
    pp.default_code ILIKE :q_like
    OR pt.default_code ILIKE :q_like
    OR pp.name ILIKE :q_like
    OR pt.name ILIKE :q_like
    OR EXISTS (
        SELECT 1
        FROM product_variant_attribute_value pvav_s
        JOIN product_template_attribute_line ptal_s ON ptal_s.id = pvav_s.attribute_line_id
        JOIN product_attribute pa_s ON pa_s.id = ptal_s.attribute_id
        JOIN product_attribute_value pav_s ON pav_s.id = pvav_s.attribute_value_id
        WHERE pvav_s.product_id = pp.id
          AND (pa_s.name ILIKE :q_like OR pav_s.name ILIKE :q_like)
    )
  )
  AND NOT (
    lower(pt.default_code) = lower(:q_exact)
    AND lower(pp.default_code) <> lower(pt.default_code)
    AND EXISTS (
        SELECT 1
        FROM product_product pp_exact
        WHERE pp_exact.template_id = pt.id
          AND pp_exact.active IS TRUE
          AND lower(pp_exact.default_code) = lower(pt.default_code)
    )
  )
ORDER BY
    CASE
        WHEN lower(pp.default_code) = lower(:q_exact) THEN 0
        WHEN lower(pt.default_code) = lower(:q_exact) THEN 1
        WHEN pp.default_code ILIKE :q_prefix THEN 2
        WHEN pt.default_code ILIKE :q_prefix THEN 3
        WHEN pp.default_code ILIKE :q_like THEN 4
        ELSE 5
    END,
    pp.default_code
LIMIT :limit
""")


def _opt_str(v: object | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _valid_media_str(v: object | None) -> str | None:
    s = _opt_str(v)
    if s is None or s.lower() in ("nan", "none", "null"):
        return None
    return s


def _gallery_list(v: object | None) -> list[str] | None:
    if v is None:
        return None
    candidates: list[object]
    if isinstance(v, list | tuple):
        candidates = list(v)
    elif isinstance(v, dict):
        raw = v.get("images") or v.get("gallery") or v.get("items") or []
        candidates = list(raw) if isinstance(raw, list | tuple) else [raw]
    else:
        candidates = [v]
    out: list[str] = []
    for item in candidates:
        s = _valid_media_str(item)
        if s and s not in out:
            out.append(s)
    return out or None


def _image_or_placeholder(image: object | None, gallery: object | None = None) -> str:
    return (
        _valid_media_str(image)
        or (_gallery_list(gallery) or [None])[0]
        or PLACEHOLDER_PRODUCT_IMAGE
    )


def _fetch_template_attribute_types(
    db: Session, tmpl_id: int
) -> tuple[dict[str, str], list[str]]:
    """{ nombre_atributo: attr_type }, y lista de nombres con tipo color."""
    try:
        rows = db.execute(
            _TEMPLATE_ATTR_TYPES_SQL, {"tmpl_id": tmpl_id}
        ).mappings().all()
    except ProgrammingError as e:
        logger.warning("Tipos de atributo por template omitidos: %s", e)
        return {}, []
    types: dict[str, str] = {}
    for r in rows:
        an = _opt_str(r.get("attr_name"))
        if not an:
            continue
        raw = r.get("attr_type")
        typ = str(raw).strip().lower() if raw is not None else "select"
        types[an] = typ if typ in ("color", "select") else "select"
    color_keys = [k for k, v in types.items() if v == "color"]
    return types, color_keys


def _fetch_attribute_value_specs(db: Session, tmpl_id: int) -> dict[str, dict[str, AttributeValueSpecOut]]:
    try:
        rows = db.execute(_VALUE_SPECS_SQL, {"tmpl_id": tmpl_id}).mappings().all()
    except ProgrammingError as e:
        logger.warning("Specs de valores de atributo omitidos: %s", e)
        return {}
    out: dict[str, dict[str, AttributeValueSpecOut]] = {}
    for r in rows:
        an = _opt_str(r.get("attr_name"))
        vn = _opt_str(r.get("val_name"))
        if not an or not vn:
            continue
        spec = AttributeValueSpecOut(
            hex=_opt_str(r.get("color_html")),
            pantone=_opt_str(r.get("pantone")),
            cmyk=_opt_str(r.get("cmyk")),
            ral=_opt_str(r.get("ral")),
        )
        if an not in out:
            out[an] = {}
        out[an][vn] = spec
    return out


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
    description_short = _opt_str(row.get("description_short"))
    keys, extra = swatch_keys_from_color_names(color_names)
    return CatalogListItemOut(
        catalog=catalog,  # type: ignore[arg-type]
        id=f"tmpl-{row['id']}",
        slug=slug,
        title=title,
        description=truncate_text(description_short, 220),
        price=format_price_eur(row.get("list_price")),  # type: ignore[arg-type]
        image=_image_or_placeholder(
            row.get("image_url"),
            row.get("gallery_jsonb"),
        ),
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


_FEATURED_RANDOM_SQL = text(f"""
WITH combined AS (
    (
        SELECT pt.id, 'impresion'::text AS catalog
        FROM product_template pt
        WHERE pt.active IS TRUE
          AND pt.default_code ~ '^A'
          AND {_TEMPLATE_HAS_ACTIVE_VARIANT_SQL.strip()}
          AND ({_IMPRESION_SQL})
        ORDER BY random()
        LIMIT :n_imp
    )
    UNION ALL
    (
        SELECT pt.id, 'rotulacion'::text AS catalog
        FROM product_template pt
        WHERE pt.active IS TRUE
          AND pt.default_code ~ '^A'
          AND {_TEMPLATE_HAS_ACTIVE_VARIANT_SQL.strip()}
          AND ({_ROTULACION_SQL})
        ORDER BY random()
        LIMIT :n_rot
    )
)
SELECT
    c.catalog,
    pt.id,
    pt.default_code,
    pt.name,
    price_info.list_price,
    price_info.image_url,
    price_info.gallery_jsonb,
    price_info.description_short
FROM combined c
JOIN product_template pt ON pt.id = c.id
LEFT JOIN LATERAL (
    SELECT pp.list_price, pp.image_url, pp.gallery_jsonb, pp.description_short
    FROM product_product pp
    WHERE pp.template_id = pt.id
      AND pp.active IS TRUE
    ORDER BY
        (CASE WHEN pp.description_short IS NOT NULL AND btrim(pp.description_short) <> '' THEN 1 ELSE 0 END) DESC,
        pp.list_price NULLS LAST,
        pp.default_code
    LIMIT 1
) price_info ON TRUE
""")


@router.get("/featured", response_model=list[CatalogListItemOut])
def catalog_featured(
    limit: int = Query(8, ge=1, le=32),
    db: Session = Depends(get_db),
):
    """Destacados aleatorios para home: mezcla impresión + rotulación (consulta acotada)."""
    if limit >= 2:
        n_imp = random.randint(1, limit - 1)
        n_rot = limit - n_imp
    else:
        n_imp, n_rot = limit, 0

    try:
        rows = db.execute(
            _FEATURED_RANDOM_SQL,
            {"n_imp": n_imp, "n_rot": n_rot},
        ).mappings().all()
    except ProgrammingError as e:
        logger.exception("Catálogo featured: error de consulta %s", e)
        raise HTTPException(
            status_code=503,
            detail="Catálogo no disponible (error al leer la base de datos).",
        ) from e

    if not rows:
        return []

    shuffled = list(rows)
    random.shuffle(shuffled)

    ids = [int(r["id"]) for r in shuffled]
    colors = _fetch_color_map(db, ids)
    return [
        _row_to_list_item(r, str(r["catalog"]), colors.get(int(r["id"])))
        for r in shuffled
    ]


@router.get("/search", response_model=list[CatalogSearchResultOut])
def search_catalog(
    q: str = Query(..., min_length=2, max_length=80),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Búsqueda global por referencia, nombre o propiedades de variante."""
    needle = q.strip()
    if len(needle) < 2:
        return []
    try:
        rows = db.execute(
            _SEARCH_SQL,
            {
                "q_like": f"%{needle}%",
                "q_prefix": f"{needle}%",
                "q_exact": needle,
                "limit": limit,
            },
        ).mappings().all()
    except ProgrammingError as e:
        logger.exception("Búsqueda catálogo: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Búsqueda de catálogo no disponible.",
        ) from e

    out: list[CatalogSearchResultOut] = []
    for r in rows:
        template_code = str(r["template_code"])
        title = str(r.get("template_name") or template_code)
        raw_props = r.get("properties") or {}
        properties = {
            str(k): str(v)
            for k, v in dict(raw_props).items()
            if k is not None and v is not None and str(v).strip()
        }
        out.append(
            CatalogSearchResultOut(
                catalog=str(r["catalog"]),  # type: ignore[arg-type]
                slug=slug_from_default_code(template_code),
                title=title,
                reference=template_code,
                variantReference=str(r["variant_code"]),
                variantName=_opt_str(r.get("variant_name")),
                price=format_price_eur(r.get("variant_list_price")),  # type: ignore[arg-type]
                image=_image_or_placeholder(
                    r.get("variant_image_url"),
                    r.get("variant_gallery_jsonb"),
                ),
                properties=properties,
            )
        )
    return out


@router.get("/{catalog}", response_model=CatalogListPageOut)
def list_catalog(
    catalog: str,
    limit: int = Query(12, ge=1, le=100),
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
    attribute_value_specs = _fetch_attribute_value_specs(db, tmpl_id)
    attribute_types, color_attribute_keys = _fetch_template_attribute_types(db, tmpl_id)

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
                "list_price": vr.get("variant_list_price") or 0.0,
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
            if hx and hx.lower() not in ("", "transparent", "none"):
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

    description_short = _opt_str(row.get("description_short"))
    description_long = _opt_str(row.get("description_long"))

    base_item = _row_to_list_item(row, catalog, color_names)
    gallery = _gallery_list(row.get("gallery_jsonb"))
    return CatalogProductDetailOut(
        **base_item.model_dump(),
        descriptionShort=description_short,
        descriptionLong=description_long,
        descriptionDetail=description_short,
        characteristics=characteristics,
        fichaTecnica=[],
        cartaColores=(
            "Colores mostrados son orientativos (datos de catálogo). "
            "Confirma tono con muestra física o referencia comercial."
            if catalog == "rotulacion"
            else None
        ),
        gallery=gallery,
        variants=variants,
        attributeValueSpecs=attribute_value_specs,
        attributeTypes=attribute_types,
        colorAttributeKeys=color_attribute_keys,
    )
