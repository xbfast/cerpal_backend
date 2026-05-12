"""Esquema del catálogo de productos (compatible Odoo).

Crea las tablas, índices, seed inicial de categorías y la vista
`v_product_full`. Es idempotente: si las tablas ya existen (por haberse
creado previamente con scripts de migración manuales) no se vuelven a
crear ni se duplican datos.

Tablas:
- product_category
- product_attribute
- product_attribute_value
- product_template
- product_product
- product_template_category
- product_template_attribute_line
- product_variant_attribute_value
- migration_log

Vista:
- v_product_full

Revision ID: 004_catalog_schema
Revises: 003_fix_test_user_email
Create Date: 2026-05-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_catalog_schema"
down_revision: Union[str, None] = "003_fix_test_user_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CREATE_TABLES_SQL = """
-- 1. Categorías (product.category en Odoo)
CREATE TABLE IF NOT EXISTS product_category (
    id              SERIAL PRIMARY KEY,
    category_code   VARCHAR(20)  NOT NULL UNIQUE,
    name            VARCHAR(150) NOT NULL,
    complete_name   VARCHAR(300),
    parent_id       INTEGER REFERENCES product_category(id) ON DELETE RESTRICT,
    sequence        INTEGER DEFAULT 10,
    odoo_categ_id   INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_category_parent ON product_category(parent_id);
CREATE INDEX IF NOT EXISTS idx_category_code   ON product_category(category_code);

-- 2. Atributos (product.attribute en Odoo)
CREATE TABLE IF NOT EXISTS product_attribute (
    id              SERIAL PRIMARY KEY,
    code            INTEGER      NOT NULL UNIQUE,
    name            VARCHAR(150) NOT NULL,
    attr_type       VARCHAR(20)  NOT NULL DEFAULT 'select'
                        CHECK (attr_type IN ('select', 'color')),
    create_variant  VARCHAR(20)  DEFAULT 'always'
                        CHECK (create_variant IN ('always', 'dynamic', 'no_variant')),
    odoo_attr_id    INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_attribute_code ON product_attribute(code);

-- 3. Valores de atributo (product.attribute.value en Odoo)
CREATE TABLE IF NOT EXISTS product_attribute_value (
    id              SERIAL PRIMARY KEY,
    attribute_id    INTEGER      NOT NULL REFERENCES product_attribute(id) ON DELETE CASCADE,
    line_id         INTEGER      NOT NULL,
    name            VARCHAR(255) NOT NULL,
    color_html      VARCHAR(20),
    pantone         VARCHAR(50),
    cmyk            VARCHAR(50),
    ral             VARCHAR(20),
    odoo_value_id   INTEGER,
    UNIQUE (attribute_id, line_id)
);
CREATE INDEX IF NOT EXISTS idx_attr_value_attr ON product_attribute_value(attribute_id);

-- 4. Product template (product.template en Odoo)
CREATE TABLE IF NOT EXISTS product_template (
    id              SERIAL PRIMARY KEY,
    default_code    VARCHAR(64)  NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    active          BOOLEAN      DEFAULT TRUE,
    odoo_tmpl_id    INTEGER,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_template_code ON product_template(default_code);

-- 5. Producto / variante (product.product en Odoo)
CREATE TABLE IF NOT EXISTS product_product (
    id              SERIAL PRIMARY KEY,
    template_id     INTEGER      NOT NULL REFERENCES product_template(id) ON DELETE CASCADE,
    default_code    VARCHAR(64)  NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    list_price      NUMERIC(10,4),
    active          BOOLEAN      DEFAULT TRUE,
    image_url       VARCHAR(500),
    gallery_jsonb   JSONB,
    odoo_product_id INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_product_template ON product_product(template_id);
CREATE INDEX IF NOT EXISTS idx_product_code     ON product_product(default_code);

-- 6. Categorías por producto (many-to-many)
CREATE TABLE IF NOT EXISTS product_template_category (
    id          SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES product_template(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES product_category(id) ON DELETE CASCADE,
    line_id     INTEGER,
    UNIQUE (template_id, category_id)
);
CREATE INDEX IF NOT EXISTS idx_tmpl_cat_tmpl ON product_template_category(template_id);
CREATE INDEX IF NOT EXISTS idx_tmpl_cat_cat  ON product_template_category(category_id);

-- 7. Líneas de atributo por template (product.template.attribute.line)
CREATE TABLE IF NOT EXISTS product_template_attribute_line (
    id              SERIAL PRIMARY KEY,
    template_id     INTEGER NOT NULL REFERENCES product_template(id) ON DELETE CASCADE,
    attribute_id    INTEGER NOT NULL REFERENCES product_attribute(id) ON DELETE CASCADE,
    sequence        INTEGER DEFAULT 10,
    UNIQUE (template_id, attribute_id)
);
CREATE INDEX IF NOT EXISTS idx_tmpl_attr_line_tmpl ON product_template_attribute_line(template_id);
CREATE INDEX IF NOT EXISTS idx_tmpl_attr_line_attr ON product_template_attribute_line(attribute_id);

-- 8. Valores por variante (product.template.attribute.value en Odoo)
CREATE TABLE IF NOT EXISTS product_variant_attribute_value (
    id                  SERIAL PRIMARY KEY,
    product_id          INTEGER NOT NULL REFERENCES product_product(id) ON DELETE CASCADE,
    attribute_line_id   INTEGER NOT NULL REFERENCES product_template_attribute_line(id) ON DELETE CASCADE,
    attribute_value_id  INTEGER NOT NULL REFERENCES product_attribute_value(id) ON DELETE CASCADE,
    sequence            INTEGER DEFAULT 1,
    UNIQUE (product_id, attribute_line_id)
);
CREATE INDEX IF NOT EXISTS idx_var_attr_val_prod ON product_variant_attribute_value(product_id);
CREATE INDEX IF NOT EXISTS idx_var_attr_val_line ON product_variant_attribute_value(attribute_line_id);

-- 9. Log de migración
CREATE TABLE IF NOT EXISTS migration_log (
    id          SERIAL PRIMARY KEY,
    run_at      TIMESTAMP DEFAULT NOW(),
    step        VARCHAR(120),
    records_in  INTEGER,
    records_ok  INTEGER,
    records_err INTEGER,
    notes       TEXT
);
"""


_SEED_CATEGORIES_SQL = """
-- Nivel 1 — Categorías raíz
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('1',  'Rotulación',                    'Rotulación',                    NULL, 10),
('2',  'Impresión Digital y Laminado',  'Impresión Digital y Laminado',  NULL, 20),
('3',  'Tintas',                        'Tintas',                        NULL, 30),
('4',  'Maquinaria',                    'Maquinaria',                    NULL, 40),
('5',  'Sublimación y Textil',          'Sublimación y Textil',          NULL, 50),
('6',  'Accesorios',                    'Accesorios',                    NULL, 60),
('10', 'Tintas (web)',                  'Tintas (web)',                   NULL, 70)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Rotulación
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('1.1',  'Vinilo Opaco',               'Rotulación / Vinilo Opaco',               (SELECT id FROM product_category WHERE category_code='1'), 10),
('1.2',  'Vinilo Ácido',               'Rotulación / Vinilo Ácido',               (SELECT id FROM product_category WHERE category_code='1'), 20),
('1.3',  'Vinilo Translúcido',         'Rotulación / Vinilo Translúcido',         (SELECT id FROM product_category WHERE category_code='1'), 30),
('1.4',  'Car Wrapping',               'Rotulación / Car Wrapping',               (SELECT id FROM product_category WHERE category_code='1'), 40),
('1.5',  'Vinilo Pizarra',             'Rotulación / Vinilo Pizarra',             (SELECT id FROM product_category WHERE category_code='1'), 50),
('1.6',  'Transportadores',            'Rotulación / Transportadores',            (SELECT id FROM product_category WHERE category_code='1'), 60),
('1.7',  'Vinilo Imantado',            'Rotulación / Vinilo Imantado',            (SELECT id FROM product_category WHERE category_code='1'), 70),
('1.8',  'Lámina Solar',               'Rotulación / Lámina Solar',               (SELECT id FROM product_category WHERE category_code='1'), 80),
('1.9',  'Reflectantes',               'Rotulación / Reflectantes',               (SELECT id FROM product_category WHERE category_code='1'), 90),
('1.10', 'Metalizados',                'Rotulación / Metalizados',                (SELECT id FROM product_category WHERE category_code='1'), 100),
('1.11', 'Máscaras',                   'Rotulación / Máscaras',                   (SELECT id FROM product_category WHERE category_code='1'), 110)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Impresión Digital y Laminado
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('2.1', 'Impresión Digital',  'Impresión Digital y Laminado / Impresión Digital',  (SELECT id FROM product_category WHERE category_code='2'), 10),
('2.2', 'Laminación',         'Impresión Digital y Laminado / Laminación',         (SELECT id FROM product_category WHERE category_code='2'), 20)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Tintas
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('3.1', 'Roland',       'Tintas / Roland',       (SELECT id FROM product_category WHERE category_code='3'), 10),
('3.2', 'Alternativas', 'Tintas / Alternativas', (SELECT id FROM product_category WHERE category_code='3'), 20),
('3.3', 'Epson',        'Tintas / Epson',         (SELECT id FROM product_category WHERE category_code='3'), 30)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Maquinaria
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('4.1', 'Roland',    'Maquinaria / Roland',    (SELECT id FROM product_category WHERE category_code='4'), 10),
('4.2', 'Epson',     'Maquinaria / Epson',     (SELECT id FROM product_category WHERE category_code='4'), 20),
('4.3', 'Stahls',    'Maquinaria / Stahls',    (SELECT id FROM product_category WHERE category_code='4'), 30),
('4.4', 'Repuestos', 'Maquinaria / Repuestos', (SELECT id FROM product_category WHERE category_code='4'), 40)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Sublimación y Textil
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('5.1', 'Sublimación',              'Sublimación y Textil / Sublimación',              (SELECT id FROM product_category WHERE category_code='5'), 10),
('5.2', 'Vinilo Textil',            'Sublimación y Textil / Vinilo Textil',            (SELECT id FROM product_category WHERE category_code='5'), 20),
('5.3', 'Vinilo Impresión Textil',  'Sublimación y Textil / Vinilo Impresión Textil',  (SELECT id FROM product_category WHERE category_code='5'), 30)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Accesorios
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('6.1', 'Cintas Adhesivas', 'Accesorios / Cintas Adhesivas', (SELECT id FROM product_category WHERE category_code='6'), 10),
('6.2', 'Expositores',      'Accesorios / Expositores',      (SELECT id FROM product_category WHERE category_code='6'), 20),
('6.3', 'Otros',            'Accesorios / Otros',            (SELECT id FROM product_category WHERE category_code='6'), 30)
ON CONFLICT (category_code) DO NOTHING;

-- Nivel 2 — Tintas web (categoría especial)
INSERT INTO product_category (category_code, name, complete_name, parent_id, sequence) VALUES
('10.6', 'Tintas Compatibles', 'Tintas (web) / Tintas Compatibles', (SELECT id FROM product_category WHERE category_code='10'), 10)
ON CONFLICT (category_code) DO NOTHING;
"""


_CREATE_VIEW_SQL = """
CREATE OR REPLACE VIEW v_product_full AS
SELECT
    pp.default_code                     AS code,
    pp.name                             AS product_name,
    pt.default_code                     AS template_code,
    string_agg(DISTINCT pc.complete_name, ' | ' ORDER BY pc.complete_name) AS categories,
    pa.name                             AS attribute_name,
    pav.name                            AS attribute_value,
    pav.color_html,
    pp.list_price,
    pp.active
FROM product_product pp
JOIN product_template pt                    ON pt.id = pp.template_id
LEFT JOIN product_template_category ptc     ON ptc.template_id = pt.id
LEFT JOIN product_category pc               ON pc.id = ptc.category_id
LEFT JOIN product_variant_attribute_value pvav ON pvav.product_id = pp.id
LEFT JOIN product_template_attribute_line ptal ON ptal.id = pvav.attribute_line_id
LEFT JOIN product_attribute pa              ON pa.id = ptal.attribute_id
LEFT JOIN product_attribute_value pav       ON pav.id = pvav.attribute_value_id
GROUP BY pp.default_code, pp.name, pt.default_code, pa.code, pa.name, pav.name, pav.color_html, pp.list_price, pp.active
ORDER BY pp.default_code, pa.code;
"""


_DROP_SQL = """
DROP VIEW IF EXISTS v_product_full;
DROP TABLE IF EXISTS migration_log;
DROP TABLE IF EXISTS product_variant_attribute_value;
DROP TABLE IF EXISTS product_template_attribute_line;
DROP TABLE IF EXISTS product_template_category;
DROP TABLE IF EXISTS product_product;
DROP TABLE IF EXISTS product_template;
DROP TABLE IF EXISTS product_attribute_value;
DROP TABLE IF EXISTS product_attribute;
DROP TABLE IF EXISTS product_category;
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_CREATE_TABLES_SQL))
    bind.execute(sa.text(_SEED_CATEGORIES_SQL))
    bind.execute(sa.text(_CREATE_VIEW_SQL))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_DROP_SQL))
