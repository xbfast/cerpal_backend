"""
migracion_catalogo.py
─────────────────────
Migración completa de Excel → PostgreSQL (compatible Odoo)

Fuentes:
  · Atributos.xlsx               → atributos, valores, variantes, imágenes
  · Catagorias_Articulos_Web.xlsx → categorías y asignación por producto

Ejecutar: python migracion_catalogo.py
Requisito previo: ejecutar schema.sql en la base de datos primero.
"""

import os
import sys
import pandas as pd
import psycopg2
import warnings
warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "database": "cerpal",
    "user":     "cerpal",
    "password": "cerpal",
}

EXCEL_ATRIBUTOS  = "data/Atributos.xlsx"
EXCEL_CATEGORIAS = "data/Catagorias_Articulos_Web.xlsx"

# ══════════════════════════════════════════════════════════════

def get_conn():
    return psycopg2.connect(
        host     = DB_CONFIG["host"],
        port     = DB_CONFIG["port"],
        dbname   = DB_CONFIG["database"],
        user     = DB_CONFIG["user"],
        password = DB_CONFIG["password"],
    )

def sep(title=""):
    print("\n" + "─" * 58)
    if title:
        print(f"  {title}")
        print("─" * 58)

def clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s else None


def normalize_product_code(v):
    s = clean(v)
    if s is None:
        return None
    if s.upper().startswith("P_A"):
        return s[2:]
    return s


def normalize_category_code(v):
    s = clean(v)
    if s is None:
        return None
    if s.endswith(".0"):
        return s[:-2]
    return s


# ──────────────────────────────────────────────────────────────
# PASO 0 · Test de conexión
# ──────────────────────────────────────────────────────────────
def test_connection():
    sep("PASO 0 · Probando conexión")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                print("✅ Conectado:", cur.fetchone()[0][:60])
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────────────────────
# PASO 1 · Cargar todos los Excel
# ──────────────────────────────────────────────────────────────
def load_excel():
    sep("PASO 1 · Cargando Excel")

    # ── Articulos Precio ──
    df_precio = pd.read_excel(EXCEL_ATRIBUTOS, sheet_name="Articulos Precio", header=0)
    df_precio.columns = [str(c).strip() for c in df_precio.columns]
    df_precio = df_precio.rename(columns={
        "Número de artículo":      "code",
        "Descripción de artículo": "name",
        "Activo":                  "active",
        "Producto Padre":          "padre",
        "Precio de Venta":         "list_price",
    })[["code", "name", "active", "padre", "list_price"]].copy()
    df_precio = df_precio.dropna(subset=["code"])
    df_precio["code"]       = df_precio["code"].astype(str).str.strip()
    df_precio["padre"]      = df_precio["padre"].fillna(df_precio["code"]).astype(str).str.strip()
    df_precio["list_price"] = pd.to_numeric(df_precio["list_price"], errors="coerce")
    df_precio["active"]     = df_precio["active"].apply(
        lambda x: False if clean(x) and clean(x).lower() in ["no", "false", "0"] else True
    )

    # ── Atributos (variante × atributo × valor) ──
    df_attrs = pd.read_excel(EXCEL_ATRIBUTOS, sheet_name="Atributos", header=0)
    df_attrs.columns = [str(c).strip() for c in df_attrs.columns]
    df_attrs = df_attrs.rename(columns={
        "Code":            "code",
        "Nombre":          "name",
        "Cód. Atributo":   "attr_code",
        "Nombre Atributo": "attr_name",
        "LineId":          "seq",
        "Cód. Valor":      "value_id",
        "Nombre Valor":    "value_name",
        "Padre":           "padre",
        "Imagen":          "imagen",
        "GALERIA - JSONB": "galeria",
        "Descripción Corta": "desc_corta",
        "Descripción Larga": "desc_larga",
    })
    df_attrs["code"]      = df_attrs["code"].astype(str).str.strip()
    df_attrs["padre"]     = df_attrs["padre"].fillna(df_attrs["code"]).astype(str).str.strip()
    df_attrs["attr_code"] = pd.to_numeric(df_attrs["attr_code"], errors="coerce")
    df_attrs["value_id"]  = pd.to_numeric(df_attrs["value_id"],  errors="coerce")
    df_attrs["seq"]       = pd.to_numeric(df_attrs["seq"],        errors="coerce").fillna(1)
    df_attrs = df_attrs.dropna(subset=["attr_code", "value_id"])
    df_attrs["attr_code"] = df_attrs["attr_code"].astype(int)
    df_attrs["value_id"]  = df_attrs["value_id"].astype(int)
    df_attrs["seq"]       = df_attrs["seq"].astype(int)

    # ── Nombre y tipo de atributo (fuente de verdad) ──
    df_tipos = pd.read_excel(EXCEL_ATRIBUTOS, sheet_name="Nombre y tipo de atributo", header=0)
    df_tipos.columns = [str(c).strip() for c in df_tipos.columns]
    df_tipos = df_tipos.rename(columns={
        "Code":          "code",
        "Name":          "name",
        "Tipo Atributo": "tipo",
    })[["code", "name", "tipo"]].dropna(subset=["code", "name"])
    df_tipos["code"] = pd.to_numeric(df_tipos["code"], errors="coerce")
    df_tipos = df_tipos.dropna(subset=["code"])
    df_tipos["code"] = df_tipos["code"].astype(int)

    # ── Atributos Valores ──
    df_vals = pd.read_excel(EXCEL_ATRIBUTOS, sheet_name="Atributos Valores", header=0)
    df_vals.columns = [str(c).strip() for c in df_vals.columns]
    df_vals = df_vals.rename(columns={
        "Code":                  "attr_code",
        "LineId":                "line_id",
        "Valor":                 "value_name",
        "Codigo HTML del color": "color_html",
        "Pantone":               "pantone",
        "CMYK":                  "cmyk",
        "RAL":                   "ral",
    })
    df_vals["attr_code"] = pd.to_numeric(df_vals["attr_code"], errors="coerce")
    df_vals["line_id"]   = pd.to_numeric(df_vals["line_id"],   errors="coerce")
    df_vals = df_vals.dropna(subset=["attr_code", "line_id", "value_name"])
    df_vals["attr_code"] = df_vals["attr_code"].astype(int)
    df_vals["line_id"]   = df_vals["line_id"].astype(int)
    for col in ["value_name", "color_html", "pantone", "cmyk", "ral"]:
        df_vals[col] = df_vals[col].apply(clean)

    # ── Categorias por producto ──
    df_cat = pd.read_excel(EXCEL_CATEGORIAS, sheet_name="Categorias por producto", header=0)
    df_cat.columns = [str(c).strip() for c in df_cat.columns]
    df_cat = df_cat.rename(columns={
        "Code":           "code",
        "Id. Categoría":  "cat_code",
        "LineId":         "line_id",
    })[["code", "cat_code", "line_id"]].dropna(subset=["code", "cat_code"])
    df_cat["code"]     = df_cat["code"].apply(normalize_product_code)
    df_cat["cat_code"] = df_cat["cat_code"].apply(normalize_category_code)
    df_cat = df_cat.dropna(subset=["code", "cat_code"])
    df_cat["line_id"]  = pd.to_numeric(df_cat["line_id"], errors="coerce").fillna(1).astype(int)

    print(f"  Articulos Precio:          {len(df_precio):>6,} filas")
    print(f"  Atributos (var × attr):    {len(df_attrs):>6,} filas")
    print(f"  Tipos de atributo:         {len(df_tipos):>6,} filas")
    print(f"  Valores de atributo:       {len(df_vals):>6,} filas")
    print(f"  Categorías por producto:   {len(df_cat):>6,} filas")

    return df_precio, df_attrs, df_tipos, df_vals, df_cat


# ──────────────────────────────────────────────────────────────
# PASO 2 · Atributos — desde hoja "Nombre y tipo de atributo"
# ──────────────────────────────────────────────────────────────
# Atributos que en Odoo no generan variante por sí solos
NO_VARIANT = {23, 24, 25, 26, 27, 31, 37, 41, 55, 56, 100}

def migrate_attributes(df_tipos):
    sep("PASO 2 · Atributos")
    with get_conn() as conn:
        cur = conn.cursor()
        ok = 0
        for _, r in df_tipos.iterrows():
            tipo      = (r["tipo"] or "").strip().lower()
            attr_type = "color" if tipo == "color" else "select"
            create_v  = "no_variant" if int(r["code"]) in NO_VARIANT else "always"
            cur.execute("""
                INSERT INTO product_attribute (code, name, attr_type, create_variant)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name           = EXCLUDED.name,
                    attr_type      = EXCLUDED.attr_type,
                    create_variant = EXCLUDED.create_variant
            """, (int(r["code"]), r["name"], attr_type, create_v))
            ok += 1
        conn.commit()
        cur.close()
    print(f"✅ {ok} atributos insertados/actualizados")


# ──────────────────────────────────────────────────────────────
# PASO 3 · Valores de atributo
# ──────────────────────────────────────────────────────────────
def migrate_attribute_values(df_vals, df_attrs):
    sep("PASO 3 · Valores de atributo")

    # La hoja "Atributos Valores" trae specs (color/Pantone/CMYK/RAL), pero en
    # algunos atributos no lista todos los valores usados por producto. La hoja
    # "Atributos" sí trae la relación attr_code/value_id/value_name completa.
    values_by_key = {}
    for _, r in df_vals.iterrows():
        key = (int(r["attr_code"]), int(r["line_id"]))
        values_by_key[key] = {
            "attr_code": key[0],
            "line_id": key[1],
            "value_name": clean(r["value_name"]),
            "color_html": clean(r["color_html"]),
            "pantone": clean(r["pantone"]),
            "cmyk": clean(r["cmyk"]),
            "ral": clean(r["ral"]),
            "source": "Atributos Valores",
        }

    completed_from_attrs = 0
    for _, r in df_attrs.iterrows():
        if clean(r.get("value_name")) is None:
            continue
        key = (int(r["attr_code"]), int(r["value_id"]))
        if key in values_by_key:
            continue
        values_by_key[key] = {
            "attr_code": key[0],
            "line_id": key[1],
            "value_name": clean(r["value_name"]),
            "color_html": None,
            "pantone": None,
            "cmyk": None,
            "ral": None,
            "source": "Atributos",
        }
        completed_from_attrs += 1

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT code, id FROM product_attribute")
        attr_map = {r[0]: r[1] for r in cur.fetchall()}

        ok = skipped = 0
        for r in values_by_key.values():
            attr_id = attr_map.get(r["attr_code"])
            if not attr_id:
                skipped += 1
                continue
            cur.execute("""
                INSERT INTO product_attribute_value
                    (attribute_id, line_id, name, color_html, pantone, cmyk, ral)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (attribute_id, line_id) DO UPDATE SET
                    name       = EXCLUDED.name,
                    color_html = EXCLUDED.color_html,
                    pantone    = EXCLUDED.pantone,
                    cmyk       = EXCLUDED.cmyk,
                    ral        = EXCLUDED.ral
            """, (attr_id, int(r["line_id"]), r["value_name"],
                  r["color_html"], r["pantone"], r["cmyk"], r["ral"]))
            ok += 1
        conn.commit()
        cur.close()
    print(
        f"✅ {ok} valores insertados  |  {skipped} omitidos  |  "
        f"{completed_from_attrs} completados desde hoja Atributos"
    )


# ──────────────────────────────────────────────────────────────
# PASO 4 · Templates y variantes
#   Templates = agrupación por "Padre" de Articulos Precio
#   Variantes = los 2300 productos con precio, activo, imagen
# ──────────────────────────────────────────────────────────────
def migrate_products(df_precio, df_attrs):
    sep("PASO 4 · Templates y variantes")

    # Imagen, galería y descripciones desde hoja Atributos (por variante)
    img_map       = {}
    gal_map       = {}
    desc_corta_map = {}
    desc_larga_map = {}
    for _, r in df_attrs.drop_duplicates("code").iterrows():
        if clean(r.get("imagen")):
            img_map[r["code"]] = clean(r["imagen"])
        if clean(r.get("galeria")):
            gal_map[r["code"]] = clean(r["galeria"])
        if clean(r.get("desc_corta")):
            desc_corta_map[r["code"]] = clean(r["desc_corta"])
        if clean(r.get("desc_larga")):
            desc_larga_map[r["code"]] = clean(r["desc_larga"])

    # Un template por cada valor único de "padre".
    # Ordenar para que .first() prefiera filas con descripción no vacía (evita NOT NULL en name).
    dfw = df_precio.copy()
    dfw["_name_ok"] = dfw["name"].map(lambda x: 0 if clean(x) else 1)
    templates = (
        dfw.sort_values(["padre", "_name_ok", "code"])
        .groupby("padre", as_index=False)
        .first()
        .rename(columns={"padre": "tmpl_code", "name": "tmpl_name"})
        .drop(columns=["_name_ok"], errors="ignore")
    )

    def _non_empty_name(name, code_fallback: str) -> str:
        n = clean(name)
        if n:
            return n[:255]
        c = str(code_fallback).strip()
        return (f"Artículo {c}" if c else "Sin descripción")[:255]

    templates["tmpl_name"] = templates.apply(
        lambda r: _non_empty_name(r["tmpl_name"], r["tmpl_code"]),
        axis=1,
    )

    with get_conn() as conn:
        cur = conn.cursor()

        # Insertar templates
        for _, t in templates.iterrows():
            cur.execute("""
                INSERT INTO product_template (default_code, name, active)
                VALUES (%s, %s, %s)
                ON CONFLICT (default_code) DO UPDATE SET
                    name       = EXCLUDED.name,
                    active     = EXCLUDED.active,
                    updated_at = NOW()
            """, (t["tmpl_code"], t["tmpl_name"], bool(t["active"])))
        conn.commit()

        cur.execute("SELECT default_code, id FROM product_template")
        tmpl_map = {r[0]: r[1] for r in cur.fetchall()}

        # Insertar variantes
        ok = skipped = 0
        for _, r in df_precio.iterrows():
            tmpl_id = tmpl_map.get(r["padre"])
            if not tmpl_id:
                skipped += 1
                continue
            precio   = float(r["list_price"]) if pd.notna(r["list_price"]) else None
            imagen   = img_map.get(r["code"])
            galeria  = gal_map.get(r["code"])
            desc_c   = desc_corta_map.get(r["code"])
            desc_l   = desc_larga_map.get(r["code"])
            var_name = _non_empty_name(r.get("name"), r["code"])
            cur.execute("""
                INSERT INTO product_product
                    (template_id, default_code, name, list_price, active,
                     image_url, gallery_jsonb, description_short, description_long)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (default_code) DO UPDATE SET
                    name              = EXCLUDED.name,
                    list_price        = EXCLUDED.list_price,
                    active            = EXCLUDED.active,
                    image_url         = EXCLUDED.image_url,
                    gallery_jsonb     = EXCLUDED.gallery_jsonb,
                    description_short = EXCLUDED.description_short,
                    description_long  = EXCLUDED.description_long
            """, (tmpl_id, r["code"], var_name, precio, bool(r["active"]),
                  imagen, galeria, desc_c, desc_l))
            ok += 1

        conn.commit()
        cur.close()

    print(f"✅ {len(templates)} templates insertados")
    print(f"✅ {ok} variantes insertadas  |  {skipped} omitidas")
    return tmpl_map


# ──────────────────────────────────────────────────────────────
# PASO 5 · Categorías por producto
#   Many-to-many: template → categoría
#   La asignación viene del código del producto; subimos al template padre
# ──────────────────────────────────────────────────────────────
def migrate_categories(df_cat, tmpl_map, df_precio):
    sep("PASO 5 · Categorías por producto")

    # Mapa código variante → padre (template)
    code_padre = dict(zip(df_precio["code"], df_precio["padre"]))

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT category_code, id FROM product_category")
        cat_map = {r[0]: r[1] for r in cur.fetchall()}

        ok = skipped = 0
        for _, r in df_cat.iterrows():
            padre   = code_padre.get(r["code"], r["code"])
            tmpl_id = tmpl_map.get(padre)
            cat_id  = cat_map.get(r["cat_code"])

            if not tmpl_id or not cat_id:
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO product_template_category (template_id, category_id, line_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (template_id, category_id) DO UPDATE SET
                    line_id = EXCLUDED.line_id
            """, (tmpl_id, cat_id, int(r["line_id"])))
            ok += 1

        conn.commit()
        cur.close()

    print(f"✅ {ok} asignaciones categoría→template  |  {skipped} omitidas")
    if skipped > 0:
        print(f"   (omitidas = categorías del Excel no presentes en schema.sql)")


# ──────────────────────────────────────────────────────────────
# PASO 6 · Líneas de atributo por template
# ──────────────────────────────────────────────────────────────
def migrate_attr_lines(df_attrs, tmpl_map):
    sep("PASO 6 · Líneas de atributo por template")

    code_padre = dict(zip(df_attrs["code"], df_attrs["padre"]))

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT code, id FROM product_attribute")
        attr_map = {r[0]: r[1] for r in cur.fetchall()}

        # Deduplicar: primer seq encontrado por (template, atributo)
        pair_map = {}
        for _, r in df_attrs.iterrows():
            padre   = code_padre.get(r["code"], r["code"])
            tmpl_id = tmpl_map.get(padre)
            attr_id = attr_map.get(r["attr_code"])
            if tmpl_id and attr_id:
                key = (tmpl_id, attr_id)
                if key not in pair_map:
                    pair_map[key] = int(r["seq"])

        ok = 0
        for (tmpl_id, attr_id), seq in pair_map.items():
            cur.execute("""
                INSERT INTO product_template_attribute_line (template_id, attribute_id, sequence)
                VALUES (%s, %s, %s)
                ON CONFLICT (template_id, attribute_id) DO UPDATE SET
                    sequence = EXCLUDED.sequence
            """, (tmpl_id, attr_id, seq))
            ok += 1

        conn.commit()
        cur.close()

    print(f"✅ {ok} líneas de atributo insertadas")


# ──────────────────────────────────────────────────────────────
# PASO 7 · Valores seleccionados por variante
# ──────────────────────────────────────────────────────────────
def migrate_variant_values(df_attrs, tmpl_map):
    sep("PASO 7 · Valores por variante")

    code_padre = dict(zip(df_attrs["code"], df_attrs["padre"]))

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_code, id FROM product_product")
        prod_map = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("SELECT code, id FROM product_attribute")
        attr_map = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("SELECT attribute_id, line_id, id FROM product_attribute_value")
        val_map = {(r[0], r[1]): r[2] for r in cur.fetchall()}

        cur.execute("SELECT template_id, attribute_id, id FROM product_template_attribute_line")
        line_map = {(r[0], r[1]): r[2] for r in cur.fetchall()}

        seen = {}
        skipped = 0
        total = len(df_attrs)

        for i, (_, r) in enumerate(df_attrs.iterrows()):
            if i % 1000 == 0:
                print(f"  Procesando {i:,}/{total:,}...", end="\r")

            prod_id = prod_map.get(r["code"])
            attr_id = attr_map.get(r["attr_code"])
            val_id  = val_map.get((attr_id, r["value_id"])) if attr_id else None
            padre   = code_padre.get(r["code"], r["code"])
            tmpl_id = tmpl_map.get(padre)
            line_id = line_map.get((tmpl_id, attr_id)) if tmpl_id and attr_id else None

            if prod_id and line_id and val_id:
                key = (prod_id, line_id)
                if key not in seen:
                    seen[key] = (prod_id, line_id, val_id, int(r["seq"]))
            else:
                skipped += 1

        for row in seen.values():
            cur.execute("""
                INSERT INTO product_variant_attribute_value
                    (product_id, attribute_line_id, attribute_value_id, sequence)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (product_id, attribute_line_id) DO UPDATE SET
                    attribute_value_id = EXCLUDED.attribute_value_id,
                    sequence           = EXCLUDED.sequence
            """, row)

        conn.commit()
        cur.close()

    print(f"\n✅ {len(seen):,} valores de variante insertados  |  {skipped} omitidos")


# ──────────────────────────────────────────────────────────────
# PASO 8 · Validación final
# ──────────────────────────────────────────────────────────────
def validate():
    sep("PASO 8 · Validación final")

    checks = [
        (False, "Categorías",               "SELECT COUNT(*) FROM product_category"),
        (False, "Atributos",                "SELECT COUNT(*) FROM product_attribute"),
        (False, "Valores de atributo",      "SELECT COUNT(*) FROM product_attribute_value"),
        (False, "Templates",                "SELECT COUNT(*) FROM product_template"),
        (False, "Variantes / productos",    "SELECT COUNT(*) FROM product_product"),
        (False, "  · con precio",           "SELECT COUNT(*) FROM product_product WHERE list_price IS NOT NULL"),
        (False, "  · activas",              "SELECT COUNT(*) FROM product_product WHERE active = TRUE"),
        (False, "  · con imagen",           "SELECT COUNT(*) FROM product_product WHERE image_url IS NOT NULL"),
        (False, "  · con desc. corta",      "SELECT COUNT(*) FROM product_product WHERE description_short IS NOT NULL"),
        (False, "  · con desc. larga",      "SELECT COUNT(*) FROM product_product WHERE description_long IS NOT NULL"),
        (False, "Asignaciones categoría",   "SELECT COUNT(*) FROM product_template_category"),
        (False, "Líneas atributo/template", "SELECT COUNT(*) FROM product_template_attribute_line"),
        (False, "Valores por variante",     "SELECT COUNT(*) FROM product_variant_attribute_value"),
        (True,  "Templates sin categoría",  "SELECT COUNT(*) FROM product_template t WHERE NOT EXISTS (SELECT 1 FROM product_template_category WHERE template_id = t.id)"),
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for warn_if_positive, label, sql in checks:
                cur.execute(sql)
                count = cur.fetchone()[0]
                if warn_if_positive:
                    icon = "⚠️ " if count > 0 else "✅"
                else:
                    icon = "✅" if count > 0 else "⚠️ "
                print(f"  {icon}  {label:<35} {count:>8,}")

    sep()
    print("🎉 Migración completada.\n")
    print("Próximos pasos en Odoo:")
    print("  1. Inventario › Configuración › Categorías  → importar")
    print("  2. Ventas › Configuración › Atributos       → importar")
    print("  3. Inventario › Productos                   → importar")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    test_connection()
    df_precio, df_attrs, df_tipos, df_vals, df_cat = load_excel()
    migrate_attributes(df_tipos)
    migrate_attribute_values(df_vals, df_attrs)
    tmpl_map = migrate_products(df_precio, df_attrs)
    migrate_categories(df_cat, tmpl_map, df_precio)
    migrate_attr_lines(df_attrs, tmpl_map)
    migrate_variant_values(df_attrs, tmpl_map)
    validate()
