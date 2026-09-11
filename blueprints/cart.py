"""Carrito de compras. Responde HTML o JSON segun el origen de la peticion."""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from ..extensions import db
from ..helpers import current_user, parse_int, wants_json
from ..models import Product
from ..services import (
    CartError,
    add_to_cart,
    cart_summary,
    clear_cart,
    get_cart,
    remove_from_cart,
    set_quantity,
    validate_cart_stock,
)

bp = Blueprint("cart", __name__)


def _state(message: str | None = None, ok: bool = True, status: int = 200):
    """Respuesta JSON con el estado completo del carrito, calculado en el servidor."""
    cart = get_cart(current_user())
    summary = cart_summary(cart)
    items = []
    if cart:
        items = [
            {
                "product_id": i.product_id,
                "name": i.product.name,
                "quantity": i.quantity,
                "price": i.product.price,
                "line_total": i.line_total,
                "stock": i.product.stock,
            }
            for i in cart.items
        ]
    return jsonify({"ok": ok, "message": message, "summary": summary, "items": items}), status


def _respond(message: str, category: str, ok: bool = True, status: int = 200):
    if wants_json():
        return _state(message, ok=ok, status=status)
    flash(message, category)
    return redirect(request.referrer or url_for("cart.view"))


@bp.route("/")
def view():
    cart = get_cart(current_user())
    if cart:
        for warning in validate_cart_stock(cart):
            flash(warning, "info")
    return render_template("cart.html", cart=cart, summary=cart_summary(cart))


@bp.route("/agregar/<int:product_id>", methods=["POST"])
def add(product_id):
    quantity = parse_int(request.form.get("quantity"), default=1, minimum=1)
    try:
        add_to_cart(current_user(), product_id, quantity)
    except CartError as exc:
        return _respond(str(exc), "error", ok=False, status=400)

    product = db.session.get(Product, product_id)
    return _respond(f"{product.name} se agrego al carrito.", "success")


@bp.route("/actualizar/<int:product_id>", methods=["POST"])
def update(product_id):
    quantity = parse_int(request.form.get("quantity"), default=1, minimum=0)
    try:
        set_quantity(current_user(), product_id, quantity)
    except CartError as exc:
        return _respond(str(exc), "error", ok=False, status=400)
    return _respond("Carrito actualizado.", "success")


@bp.route("/eliminar/<int:product_id>", methods=["POST"])
def remove(product_id):
    try:
        remove_from_cart(current_user(), product_id)
    except CartError as exc:
        return _respond(str(exc), "error", ok=False, status=400)
    return _respond("Producto eliminado del carrito.", "info")


@bp.route("/vaciar", methods=["POST"])
def clear():
    clear_cart(current_user())
    return _respond("Vaciaste el carrito.", "info")


@bp.route("/estado")
def state():
    """Usado por el JS para refrescar el contador sin recargar la pagina."""
    return _state()
