# Cerpal — Guía de instalación y arranque

Instrucciones para levantar el proyecto desde cero: base de datos, backend (FastAPI), migraciones Alembic, frontend (Vite + React) y carga inicial del catálogo.

Estructura del repo:

```text
cerpal/
├─ cerpal_backend/     FastAPI + Postgres (Docker) + Alembic + script de catálogo
└─ cerpal_frontend/    Vite + React
```

---

## 1. Requisitos previos

- **Docker** y **Docker Compose** (Postgres, API y carga del catálogo).
- **Node.js 20+** y **npm** (frontend).
- **Python 3.12+** (solo si quieres ejecutar el script de catálogo fuera de Docker).
- Excel de origen del catálogo:
  - `Atributos.xlsx`
  - `Catagorias_Articulos_Web.xlsx`

---

## 2. Variables de entorno

### Backend

```bash
cp cerpal_backend/.env.example cerpal_backend/.env
```

Edita `cerpal_backend/.env` y, como mínimo, define un `JWT_SECRET` propio.
La `DATABASE_URL` la sobreescribe `docker-compose.yml` para que la API hable
con el contenedor `db`, así que no hace falta cambiarla en local.

### Frontend

`cerpal_frontend/.env` ya viene con la URL local correcta:

```env
VITE_API_URL=http://localhost:8000
```

Cámbiala solo si tu backend no corre en `localhost:8000`.

---

## 3. Levantar la base de datos y la API

Desde `cerpal_backend/`:

```bash
cd cerpal_backend
docker compose up -d --build
```

Esto arranca dos servicios:

- `cerpal_postgres` → Postgres 16 en `localhost:5432`
  (usuario `cerpal`, password `cerpal`, BD `cerpal`).
- `cerpal_api` → FastAPI en `http://localhost:8000`.

Comprobación:

```bash
docker compose ps
curl -s http://localhost:8000/docs | head
```

---

## 4. Ejecutar las migraciones Alembic

Migraciones disponibles en `cerpal_backend/alembic/versions/`:

- `001_initial_schema` — tablas `auth`, `contacts`, `direcciones` y enum `user_role`.
- `002_seed_test_user` — usuario de pruebas.
- `003_fix_test_user_email` — fix del email del usuario de pruebas.
- `004_catalog_schema` — esquema completo del catálogo (categorías, atributos,
  templates, productos, etc.) + seed de categorías raíz/nivel 2 + vista
  `v_product_full`.

Aplica todas con el servicio `migrate` (perfil `migrate`):

```bash
cd cerpal_backend
docker compose --profile migrate run --rm migrate
```

Esto ejecuta `alembic upgrade head` contra el contenedor de Postgres.

> Alternativa local: instala `requirements.txt` en un venv y ejecuta
> `alembic upgrade head` desde `cerpal_backend/`. La URL en `alembic.ini` ya
> apunta a `localhost:5432`.

---

## 5. Levantar el frontend

Desde `cerpal_frontend/`:

```bash
cd cerpal_frontend
npm install
npm run dev
```

Vite arrancará en `http://localhost:5173` y el frontend hablará con la API de
`http://localhost:8000`.

Otros scripts:

```bash
npm run build     # build de producción a dist/
npm run preview   # servir el build
npm run lint      # eslint
```

---

## 6. Cargar el catálogo (`migracion_catalogo.py`)

Este script lee los Excel y rellena las tablas creadas por la migración
`004_catalog_schema`.

### 6.1 Colocar los Excel

Copia los Excel en `cerpal_backend/data/`:

```text
cerpal_backend/data/Atributos.xlsx
cerpal_backend/data/Catagorias_Articulos_Web.xlsx
```

### 6.2 Ejecutar dentro de Docker (recomendado)

Hay un servicio `seed-catalog` en `docker-compose.yml` con su propia imagen
ligera (`Dockerfile.catalog` + `requirements-catalog.txt`). Monta `./data` como
volumen y se conecta directamente al contenedor `db`:

```bash
cd cerpal_backend
docker compose --profile seed-catalog run --rm seed-catalog
```

La primera vez construirá la imagen del seeder. Después solo lanza el script.

### 6.3 Alternativa: ejecutarlo en local

El script lee la conexión desde variables de entorno (`DB_HOST`, `DB_PORT`,
`DB_NAME`, `DB_USER`, `DB_PASSWORD`) con defaults a `localhost:5432` y
credenciales `cerpal/cerpal`:

```bash
cd cerpal_backend
python3 -m venv .venv_migracion
source .venv_migracion/bin/activate
pip install --upgrade pip
pip install -r requirements-catalog.txt
python migracion_catalogo.py
```

Resultado: rellena `product_category`, `product_attribute`,
`product_attribute_value`, `product_template`, `product_product`,
`product_template_category`, `product_template_attribute_line` y
`product_variant_attribute_value`.

> El proceso es idempotente para las categorías raíz/nivel 2 (ya están como
> seed en Alembic) y registra cada paso en la tabla `migration_log`.

---

## 7. Comprobación final

1. Frontend: `http://localhost:5173` carga la home y el catálogo.
2. Backend: `http://localhost:8000/docs` muestra la documentación OpenAPI.
3. Catálogo: en la BD, las consultas

   ```sql
   SELECT COUNT(*) FROM product_product;
   SELECT COUNT(*) FROM product_template;
   ```

   deberían devolver datos tras correr `migracion_catalogo.py`.

---

## 8. Resumen — orden de comandos

```bash
# 1. Variables de entorno
cp cerpal_backend/.env.example cerpal_backend/.env

# 2. Postgres + API
cd cerpal_backend
docker compose up -d --build

# 3. Migraciones Alembic
docker compose --profile migrate run --rm migrate

# 4. Frontend
cd ../cerpal_frontend
npm install
npm run dev

# 5. Catálogo (requiere los Excel en cerpal_backend/data/)
cd ../cerpal_backend
docker compose --profile seed-catalog run --rm seed-catalog
```

---

## 9. Operaciones útiles

```bash
# Ver logs de la API
docker compose logs -f api

# Reiniciar solo la API tras cambios en código
docker compose up -d --build api

# Bajar todo (manteniendo datos)
docker compose down

# Bajar todo y BORRAR la BD
docker compose down -v
```
