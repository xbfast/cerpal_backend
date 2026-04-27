"""
migracion_catalogo.py
─────────────────────
Migración de Atributos.xlsx → PostgreSQL (compatible Odoo)
Ejecutar desde Cursor: python migracion_catalogo.py

Requisito previo: haber ejecutado schema.sql en tu base de datos.
"""

import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import create_engine
import warnings
warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN — edita estos valores
# ══════════════════════════════════════════════════════════════

DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "database": "cerpal",
    "user":     "cerpal",
    "password": "cerpal",
}

EXCEL_PATH = "data/Atributos.xlsx"   # pon aquí la ruta completa si es necesario

# ══════════════════════════════════════════════════════════════

def get_conn():
    return psycopg2.connect(
        host     = DB_CONFIG["host"],
        port     = DB_CONFIG["port"],
        dbname   = DB_CONFIG["database"],
        user     = DB_CONFIG["user"],
        password = DB_CONFIG["password"],
    )

def get_engine():
    c = DB_CONFIG
    return create_engine(
        f"postgresql://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{c['database']}"
    )

def sep(title=""):
    print("\n" + "─" * 55)
    if title:
        print(f"  {title}")
        print("─" * 55)

# ──────────────────────────────────────────────────────────────
# PASO 0 · Test de conexión
# ──────────────────────────────────────────────────────────────
def test_connection():
    sep("PASO 0 · Probando conexión")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                ver = cur.fetchone()[0][:60]
                print(f"✅ Conectado: {ver}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

# ──────────────────────────────────────────────────────────────
# PASO 1 · Cargar y limpiar Excel
# ──────────────────────────────────────────────────────────────
def load_excel():
    sep("PASO 1 · Cargando Excel")

    xl = pd.ExcelFile(EXCEL_PATH)
    print(f"Hojas: {xl.sheet_names}")

    df_attrs = pd.read_excel(EXCEL_PATH, sheet_name="Atributos",        header=0)
    df_vals  = pd.read_excel(EXCEL_PATH, sheet_name="Atributos Valores", header=0)

    df_attrs.columns = [str(c).strip() for c in df_attrs.columns]
    df_vals.columns  = [str(c).strip() for c in df_vals.columns]

    # ── Hoja Atributos ──
    ATTR_COLS = {
        df_attrs.columns[0]: "product_code",
        df_attrs.columns[1]: "product_name",
        df_attrs.columns[2]: "attr_code",
        df_attrs.columns[3]: "attr_name",
        df_attrs.columns[5]: "seq",
        df_attrs.columns[6]: "value_id",
        df_attrs.columns[7]: "value_name",
        df_attrs.columns[8]: "family_code",
    }
    df_a = df_attrs.rename(columns=ATTR_COLS)[list(ATTR_COLS.values())].copy()
    df_a = df_a.dropna(subset=["product_code", "attr_code", "value_id"])
    df_a["product_code"] = df_a["product_code"].astype(str).str.strip()
    df_a["attr_code"]    = pd.to_numeric(df_a["attr_code"], errors="coerce")
    df_a["value_id"]     = pd.to_numeric(df_a["value_id"],  errors="coerce")
    df_a["seq"]          = pd.to_numeric(df_a["seq"],        errors="coerce").fillna(1)
    df_a = df_a.dropna(subset=["attr_code", "value_id"])
    df_a["attr_code"] = df_a["attr_code"].astype(int)
    df_a["value_id"]  = df_a["value_id"].astype(int)
    df_a["seq"]       = df_a["seq"].astype(int)

    # ── Hoja Atributos Valores ──
    VAL_COLS = {
        df_vals.columns[0]: "attr_code",
        df_vals.columns[1]: "attr_name",
        df_vals.columns[2]: "line_id",
        df_vals.columns[3]: "value_name",
        df_vals.columns[4]: "color_html",
        df_vals.columns[5]: "pantone",
        df_vals.columns[6]: "cmyk",
        df_vals.columns[7]: "ral",
        df_vals.columns[8]: "attr_type",
    }
    df_v = df_vals.rename(columns=VAL_COLS)[list(VAL_COLS.values())].copy()
    df_v = df_v[df_v["attr_code"] != "Code"].dropna(subset=["attr_code", "line_id", "value_name"])
    df_v["attr_code"] = pd.to_numeric(df_v["attr_code"], errors="coerce")
    df_v["line_id"]   = pd.to_numeric(df_v["line_id"],   errors="coerce")
    df_v = df_v.dropna(subset=["attr_code", "line_id"])
    df_v["attr_code"] = df_v["attr_code"].astype(int)
    df_v["line_id"]   = df_v["line_id"].astype(int)

    def cs(v):
        if pd.isna(v): return None
        return str(v).strip() or None

    for col in ["value_name", "color_html", "pantone", "cmyk", "ral", "attr_type"]:
        df_v[col] = df_v[col].apply(cs)

    print(f"✅ Filas atributos/producto: {len(df_a):,}")
    print(f"✅ Valores de atributos:     {len(df_v):,}")
    return df_a, df_v

# ──────────────────────────────────────────────────────────────
# PASO 2 · Migrar valores de atributo
# ──────────────────────────────────────────────────────────────
def migrate_attr_values(df_v):
    sep("PASO 2 · Valores de atributo")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT code, id FROM product_attribute")
        attr_map = {row[0]: row[1] for row in cur.fetchall()}

        rows, skipped = [], 0
        for _, r in df_v.iterrows():
            attr_id = attr_map.get(r["attr_code"])
            if attr_id is None:
                skipped += 1
                continue
            rows.append((
                attr_id, int(r["line_id"]), r["value_name"],
                r["color_html"], r["pantone"], r["cmyk"], r["ral"],
            ))

        execute_values(cur, """
            INSERT INTO product_attribute_value
                (attribute_id, line_id, name, color_html, pantone, cmyk, ral)
            VALUES %s
            ON CONFLICT (attribute_id, line_id) DO UPDATE SET
                name       = EXCLUDED.name,
                color_html = EXCLUDED.color_html,
                pantone    = EXCLUDED.pantone,
                cmyk       = EXCLUDED.cmyk,
                ral        = EXCLUDED.ral
        """, rows, page_size=200)
        conn.commit()
        cur.close()
    print(f"✅ {len(rows):,} valores insertados  |  {skipped} omitidos")

# ──────────────────────────────────────────────────────────────
# PASO 3 · Templates y variantes
# ──────────────────────────────────────────────────────────────
def migrate_products(df_a):
    sep("PASO 3 · Templates y variantes")

    df_products = df_a[["product_code", "product_name", "family_code"]].drop_duplicates("product_code").copy()
    df_products["family_code"] = df_products["family_code"].fillna(df_products["product_code"])

    df_templates = (
        df_products.groupby("family_code")
        .first()
        .reset_index()
        .rename(columns={"family_code": "tmpl_code", "product_name": "tmpl_name"})
    )

    with get_conn() as conn:
        cur = conn.cursor()

        # Templates
        tmpl_rows = [(r["tmpl_code"], r["tmpl_name"], r["tmpl_code"]) for _, r in df_templates.iterrows()]
        execute_values(cur, """
            INSERT INTO product_template (default_code, name, raw_source_ref)
            VALUES %s
            ON CONFLICT (default_code) DO UPDATE SET
                name           = EXCLUDED.name,
                raw_source_ref = EXCLUDED.raw_source_ref,
                updated_at     = NOW()
        """, tmpl_rows, page_size=200)

        # Variantes
        cur.execute("SELECT default_code, id FROM product_template")
        tmpl_map = {row[0]: row[1] for row in cur.fetchall()}
        fam_map  = dict(zip(df_products["product_code"], df_products["family_code"]))

        prod_rows, skipped = [], 0
        for _, r in df_products.iterrows():
            tmpl_id = tmpl_map.get(r["family_code"])
            if not tmpl_id:
                skipped += 1
                continue
            prod_rows.append((tmpl_id, r["product_code"], r["product_name"]))

        execute_values(cur, """
            INSERT INTO product_product (template_id, default_code, name)
            VALUES %s
            ON CONFLICT (default_code) DO UPDATE SET
                name        = EXCLUDED.name,
                template_id = EXCLUDED.template_id
        """, prod_rows, page_size=500)

        conn.commit()
        cur.close()

    print(f"✅ {len(tmpl_rows):,} templates  |  {len(prod_rows):,} variantes  |  {skipped} omitidos")
    return df_products, fam_map

# ──────────────────────────────────────────────────────────────
# PASO 4 · Líneas de atributo por template
# ──────────────────────────────────────────────────────────────
def migrate_attr_lines(df_a, df_products):
    sep("PASO 4 · Líneas de atributo por template")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_code, id FROM product_template")
        tmpl_map = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT code, id FROM product_attribute")
        attr_map = {r[0]: r[1] for r in cur.fetchall()}

        fam_map = dict(zip(df_products["product_code"], df_products["family_code"]))

        # Deduplicar: un solo seq por (template_id, attribute_id)
        pair_map = {}
        for _, r in df_a.iterrows():
            fam     = fam_map.get(r["product_code"])
            tmpl_id = tmpl_map.get(fam)
            attr_id = attr_map.get(r["attr_code"])
            if tmpl_id and attr_id:
                key = (tmpl_id, attr_id)
                if key not in pair_map:
                    pair_map[key] = int(r["seq"])

        rows = [(tmpl_id, attr_id, seq) for (tmpl_id, attr_id), seq in pair_map.items()]

        # Insertar de uno en uno para evitar duplicados dentro del mismo batch
        for row in rows:
            cur.execute("""
                INSERT INTO product_template_attribute_line (template_id, attribute_id, sequence)
                VALUES (%s, %s, %s)
                ON CONFLICT (template_id, attribute_id) DO UPDATE SET
                    sequence = EXCLUDED.sequence
            """, row)
        conn.commit()
        cur.close()
    print(f"✅ {len(rows):,} líneas de atributo insertadas")

# ──────────────────────────────────────────────────────────────
# PASO 5 · Valores seleccionados por variante
# ──────────────────────────────────────────────────────────────
def migrate_variant_values(df_a, df_products):
    sep("PASO 5 · Valores por variante")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT default_code, id FROM product_product")
        prod_map = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT default_code, id FROM product_template")
        tmpl_map = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT code, id FROM product_attribute")
        attr_map = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT attribute_id, line_id, id FROM product_attribute_value")
        val_map  = {(r[0], r[1]): r[2] for r in cur.fetchall()}
        cur.execute("SELECT template_id, attribute_id, id FROM product_template_attribute_line")
        line_map = {(r[0], r[1]): r[2] for r in cur.fetchall()}

        fam_map = dict(zip(df_products["product_code"], df_products["family_code"]))

        rows, skipped = [], 0
        total = len(df_a)
        for i, (_, r) in enumerate(df_a.iterrows()):
            if i % 500 == 0:
                print(f"  Procesando {i:,}/{total:,}...", end="\r")

            prod_id = prod_map.get(r["product_code"])
            attr_id = attr_map.get(r["attr_code"])
            val_id  = val_map.get((attr_id, r["value_id"])) if attr_id else None
            fam     = fam_map.get(r["product_code"])
            tmpl_id = tmpl_map.get(fam)
            line_id = line_map.get((tmpl_id, attr_id)) if tmpl_id and attr_id else None

            if prod_id and line_id and val_id:
                rows.append((prod_id, line_id, val_id, int(r["seq"])))
            else:
                skipped += 1

        # Deduplicar por (product_id, attribute_line_id)
        seen = {}
        for row in rows:
            key = (row[0], row[1])
            if key not in seen:
                seen[key] = row
        rows = list(seen.values())

        for row in rows:
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
    print(f"\n✅ {len(rows):,} valores de variante  |  {skipped} omitidos")

# ──────────────────────────────────────────────────────────────
# PASO 6 · Asignación automática de categorías
# ──────────────────────────────────────────────────────────────
def assign_categories():
    sep("PASO 6 · Asignando categorías")

    RULES = [
        (10, ["vinilo opaco", "m4 mate", "m4 brillo", "metamark m4", "nekoosa ez color", "mm-cc", "colour change"]),
        (11, ["ácido", "acido"]),
        (12, ["translúcido", "translucido", "mt600", "mt610", "mt6", "floorart", "microperforado", "mg 850"]),
        (13, ["car wrapping", "wrapping", "metacast mcx", "mdc metacast", "mdc 100", "mgc wrap"]),
        (14, ["pizarra"]),
        (15, ["transportador"]),
        (16, ["imantado"]),
        (17, ["solar"]),
        (18, ["reflectante", "m5000"]),
        (19, ["metascape m7a", "metamark mdi", "mdi a-b"]),
        (10, ["metamark m7"]),      # M7 → Vinilo Opaco (polimérico rotulación)
        (21, ["impresión digital", "md pr", "metamark md"]),
        (22, ["laminado", "metaguard mgc", "mg 850"]),
        (31, ["cartucho eco sol", "ecopure", "cartucho truevis"]),
        (41, ["plotter", "roland", "vg2", "rf-640", "rt-640", "gx-", "gx2", "sp-540", "sg 540", "xr-640", "vs-640", "xc-540", "sj 1000", "lej-640"]),
        (44, ["repuesto", "pad cutter", "assy", "inkjet", "damper"]),
        (51, ["sublimación", "sublimacion"]),
        (52, ["cad-cut", "sportsfilm", "premium plus", "sublistop", "silicone", "flock", "glitter", "effect", "vinyl efx"]),
        (53, ["impresión textil", "textil"]),
    ]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM product_template WHERE category_id IS NULL")
        templates = cur.fetchall()
        updated = 0

        for tmpl_id, name in templates:
            name_lower = (name or "").lower()
            assigned = None
            for cat_id, keywords in RULES:
                if any(kw in name_lower for kw in keywords):
                    assigned = cat_id
                    break
            if assigned:
                cur.execute(
                    "UPDATE product_template SET category_id = %s WHERE id = %s",
                    (assigned, tmpl_id)
                )
                updated += 1

        conn.commit()

        cur.execute("SELECT default_code, name FROM product_template WHERE category_id IS NULL ORDER BY name LIMIT 20")
        uncat = cur.fetchall()
        cur.close()

    print(f"✅ {updated}/{len(templates)} templates con categoría asignada")
    if uncat:
        print(f"⚠️  {len(uncat)} templates sin categoría (muestra):")
        for code, name in uncat:
            print(f"   {str(code):15s}  {(name or '')[:60]}")

# ──────────────────────────────────────────────────────────────
# PASO 7 · Validación final
# ──────────────────────────────────────────────────────────────
def validate():
    sep("PASO 7 · Validación final")

    CHECKS = [
        ("Categorías",              "SELECT COUNT(*) FROM product_category"),
        ("Atributos",               "SELECT COUNT(*) FROM product_attribute"),
        ("Valores de atributo",     "SELECT COUNT(*) FROM product_attribute_value"),
        ("Templates",               "SELECT COUNT(*) FROM product_template"),
        ("Variantes",               "SELECT COUNT(*) FROM product_product"),
        ("Líneas attr/template",    "SELECT COUNT(*) FROM product_template_attribute_line"),
        ("Valores por variante",    "SELECT COUNT(*) FROM product_variant_attribute_value"),
        ("Templates sin categoría", "SELECT COUNT(*) FROM product_template WHERE category_id IS NULL"),
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for label, sql in CHECKS:
                cur.execute(sql)
                count = cur.fetchone()[0]
                icon = "✅" if count > 0 else "⚠️ "
                if label == "Templates sin categoría":
                    icon = "⚠️ " if count > 0 else "✅"
                print(f"{icon}  {label:<32} {count:>8,}")

    sep()
    print("🎉 Migración completada.")
    print()
    print("Próximos pasos en Odoo:")
    print("  1. Inventario › Configuración › Categorías → importar categorias.csv")
    print("  2. Ventas › Configuración › Atributos → importar atributos.csv")
    print("  3. Inventario › Productos → importar productos.csv")

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    test_connection()
    df_a, df_v       = load_excel()
    migrate_attr_values(df_v)
    df_products, _   = migrate_products(df_a)
    migrate_attr_lines(df_a, df_products)
    migrate_variant_values(df_a, df_products)
    assign_categories()
    validate()
