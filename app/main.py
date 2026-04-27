import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.mail import init_mail


def _configure_logging() -> None:
    """Hace visibles los `logger.info()` de la app (p. ej. app.mail) en consola."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


_configure_logging()
from app.routers import auth as auth_router
from app.routers import catalog as catalog_router
from app.routers import contacts as contacts_router
from app.routers import direcciones as direcciones_router

app = FastAPI(title="Cerpal API", version="0.1.0")

_default_cors = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:4173,http://127.0.0.1:4173"
)
_raw = os.getenv("CORS_ORIGINS", _default_cors).strip()
_origins = [o.strip() for o in _raw.split(",") if o.strip()]
if not _origins:
    _origins = [o.strip() for o in _default_cors.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Cualquier puerto en localhost (Vite u otro dev server)
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(catalog_router.router)
app.include_router(contacts_router.router)
app.include_router(direcciones_router.router)


@app.on_event("startup")
def startup():
    init_mail()
    # Comprueba que la BD responde al arrancar (opcional pero útil en Docker)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@app.get("/")
def root():
    return {"service": "cerpal_backend", "docs": "/docs"}
