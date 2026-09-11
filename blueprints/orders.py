"""Checkout y pedidos del cliente."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..helpers import current_user, login_required, valid_email
from ..models import Order
from ..services import CartError, cart_summary, create_order, get_cart, validate_cart_stock

bp = Blueprint("orders", __name__)

PAYMENT_METHODS = {
    "transferencia": "Transferencia bancaria",
    "tarjeta": "Tarjeta de credito/debito",
    "efectivo": "Efectivo al recibir",
}

REQUIRED_FIELDS = {
    "customer_name": "Nombre y apellido",
    "customer_email": "Email",
    "customer_phone": "Telefono",
    "address_street": "Calle",
    "address_number": "Numero",
    "address_city": "Ciudad",
    "address_state": "Provincia",
    "address_zip": "Codigo postal",
}


@bp.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    user = current_user()
    cart = get_cart(user)

    if cart is None or not cart.items:
        flash("Tu carrito esta vacio.", "info")
        return redirect(url_for("main.products"))

    for warning in validate_cart_stock(cart):
        flash(warning, "info")
    if not cart.items:
        return redirect(url_for("cart.view"))

    form = {
        "customer_name": user.name,
        "customer_email": user.email,
        "customer_phone": user.phone or "",
        "address_street": "",
        "address_number": "",
        "address_city": "",
        "address_state": "",
        "address_zip": "",
        "payment_method": "transferencia",
        "notes": "",
    }

    if request.method == "POST":
        for key in form:
            form[key] = (request.form.get(key) or "").strip()

        errors = [f"Falta completar: {label}." for field, label in REQUIRED_FIELDS.items() if not form[field]]
        if form["customer_email"] and not valid_email(form["customer_email"]):
            errors.append("El email no tiene un formato valido.")
        if form["payment_method"] not in PAYMENT_METHODS:
            errors.append("Selecciona un metodo de pago valido.")

        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "checkout.html",
                    cart=cart,
                    summary=cart_summary(cart),
                    form=form,
                    payment_methods=PAYMENT_METHODS,
                ),
                400,
            )

        try:
            order = create_order(user, cart, form)
        except CartError as exc:
            flash(str(exc), "error")
            return redirect(url_for("cart.view"))

        if not user.phone and form["customer_phone"]:
            user.phone = form["customer_phone"]
            from ..extensions import db

            db.session.commit()

        flash("Recibimos tu pedido.", "success")
        return redirect(url_for("orders.confirmation", number=order.number))

    return render_template(
        "checkout.html",
        cart=cart,
        summary=cart_summary(cart),
        form=form,
        payment_methods=PAYMENT_METHODS,
    )


@bp.route("/pedido/<number>")
@login_required
def confirmation(number):
    order = Order.query.filter_by(number=number).first_or_404()
    if order.user_id != current_user().id and not current_user().is_admin:
        abort(403)
    return render_template("order_confirmation.html", order=order, payment_methods=PAYMENT_METHODS)


@bp.route("/mis-pedidos")
@login_required
def my_orders():
    orders = (
        Order.query.filter_by(user_id=current_user().id).order_by(Order.created_at.desc()).all()
    )
    return render_template("orders.html", orders=orders, payment_methods=PAYMENT_METHODS)


@bp.route("/mis-pedidos/<number>")
@login_required
def order_detail(number):
    order = Order.query.filter_by(number=number).first_or_404()
    if order.user_id != current_user().id and not current_user().is_admin:
        abort(403)
    return render_template("order_detail.html", order=order, payment_methods=PAYMENT_METHODS)
