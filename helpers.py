"""Utilidades transversales: usuario actual, decoradores de acceso y validaciones."""
from __future__ import annotations

import re
import unicodedata
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from .extensions import db
from .models import User

SESSION_USER_KEY = "user_id"


# --------------------------------------------------------------------------- #
# Sesion
# --------------------------------------------------------------------------- #
def load_current_user() -> User | None:
    """Carga el usuario de la sesion en g.user (se llama en before_request)."""
    user_id = session.get(SESSION_USER_KEY)
    g.user = db.session.get(User, user_id) if user_id else None
    if user_id and g.user is None:  # usuario borrado: limpiamos la sesion
        session.pop(SESSION_USER_KEY, None)
    return g.user


def login_user(user: User) -> None:
    """Inicia sesion regenerando el contenido de la cookie (anti session fixation).

    Se conserva el token del carrito de visitante para poder fusionarlo despues.
    """
    from .services import GUEST_CART_KEY

    guest_token = session.get(GUEST_CART_KEY)
    session.clear()
    if guest_token:
        session[GUEST_CART_KEY] = guest_token
    session[SESSION_USER_KEY] = user.id
    session.permanent = True


def logout_user() -> None:
    session.clear()


def current_user() -> User | None:
    return getattr(g, "user", None)


# --------------------------------------------------------------------------- #
# Decoradores
# --------------------------------------------------------------------------- #
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            flash("Inicia sesion para continuar.", "info")
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Inicia sesion con una cuenta de administrador.", "info")
            return redirect(url_for("auth.login", next=request.full_path))
        if not user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
# Validaciones y formato
# --------------------------------------------------------------------------- #
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match((value or "").strip()))


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "item"


def unique_slug(model, base: str, exclude_id: int | None = None) -> str:
    """Slug unico para un modelo con columna .slug."""
    from .extensions import db

    slug = slugify(base)
    candidate = slug
    index = 2
    # no_autoflush: el objeto que estamos por guardar puede estar pendiente y
    # todavia sin slug; no queremos que la consulta dispare su INSERT.
    with db.session.no_autoflush:
        while True:
            query = model.query.filter_by(slug=candidate)
            if exclude_id is not None:
                query = query.filter(model.id != exclude_id)
            if query.first() is None:
                return candidate
            candidate = f"{slug}-{index}"
            index += 1


def format_price(value) -> str:
    """Formato de moneda argentino: $ 12.345,67"""
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0.0
    entero, _, decimales = f"{value:,.2f}".partition(".")
    entero = entero.replace(",", ".")
    return f"$ {entero},{decimales}"


def parse_int(value, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def parse_float(value, default: float = 0.0, minimum: float | None = None) -> float:
    try:
        result = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def wants_json() -> bool:
    """True si la peticion viene de fetch() y espera JSON."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
