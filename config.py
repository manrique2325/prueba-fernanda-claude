"""Configuracion de la aplicacion.

La URL de la base de datos se lee de la variable de entorno DATABASE_URL, de modo
que migrar de SQLite a PostgreSQL no requiere tocar el codigo:

    export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/brillo"
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _database_uri() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return f"sqlite:///{BASE_DIR / 'instance' / 'tienda.db'}"
    # Heroku/Render entregan "postgres://", SQLAlchemy 2.x exige el driver explicito.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 dias

    # --- Identidad de la tienda (ver README para personalizar) ---
    STORE_NAME = "Brillante"
    STORE_TAGLINE = "Todo para una limpieza impecable"
    STORE_EMAIL = "hola@brillante.com.ar"
    STORE_PHONE = "+54 11 5555-0142"
    STORE_ADDRESS = "Av. Siempreviva 1234, CABA, Argentina"

    PRODUCTS_PER_PAGE = 24
    FREE_SHIPPING_THRESHOLD = 25000.0
    SHIPPING_COST = 2900.0
