"""Registro, inicio de sesion y panel del usuario."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..helpers import (
    current_user,
    login_required,
    login_user,
    logout_user,
    valid_email,
)
from ..models import Order, User
from ..services import merge_guest_cart

bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 8


def _safe_next(target: str | None) -> str:
    """Solo permite redirecciones internas (evita open redirect)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.index")


@bp.route("/registro", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("main.index"))

    form = {"name": "", "email": ""}
    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        errors = []
        if len(form["name"]) < 3:
            errors.append("Ingresa tu nombre completo (minimo 3 caracteres).")
        if not valid_email(form["email"]):
            errors.append("El email no tiene un formato valido.")
        elif User.query.filter_by(email=form["email"]).first():
            errors.append("Ya existe una cuenta con ese email.")
        if len(password) < MIN_PASSWORD_LENGTH:
            errors.append(f"La contrasena debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
        if password != confirm:
            errors.append("Las contrasenas no coinciden.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth/register.html", form=form), 400

        user = User(name=form["name"], email=form["email"], role="customer")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        merge_guest_cart(user)
        flash(f"Bienvenido/a, {user.name.split()[0]}. Tu cuenta esta lista.", "success")
        return redirect(_safe_next(request.args.get("next")))

    return render_template("auth/register.html", form=form)


@bp.route("/ingresar", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.index"))

    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()

        # Mensaje generico: no revelamos si el email existe.
        if user is None or not user.check_password(password):
            flash("Email o contrasena incorrectos.", "error")
            return render_template("auth/login.html", email=email), 401

        login_user(user)
        merge_guest_cart(user)
        flash(f"Hola de nuevo, {user.name.split()[0]}.", "success")
        destination = request.form.get("next") or request.args.get("next")
        if user.is_admin and not destination:
            destination = url_for("admin.dashboard")
        return redirect(_safe_next(destination))

    return render_template("auth/login.html", email=email)


@bp.route("/salir", methods=["POST", "GET"])
def logout():
    logout_user()
    flash("Cerraste sesion correctamente.", "info")
    return redirect(url_for("main.index"))


@bp.route("/mi-cuenta")
@login_required
def profile():
    user = current_user()
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    spent = sum(o.total for o in orders if o.status != "cancelado")
    return render_template("auth/profile.html", user=user, orders=orders[:5], total_orders=len(orders), spent=spent)


@bp.route("/mi-cuenta/datos", methods=["POST"])
@login_required
def update_profile():
    user = current_user()
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()

    if len(name) < 3:
        flash("El nombre debe tener al menos 3 caracteres.", "error")
        return redirect(url_for("auth.profile"))

    user.name = name
    user.phone = phone or None
    db.session.commit()
    flash("Datos actualizados.", "success")
    return redirect(url_for("auth.profile"))


@bp.route("/mi-cuenta/password", methods=["POST"])
@login_required
def change_password():
    user = current_user()
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    if not user.check_password(current):
        flash("La contrasena actual no es correcta.", "error")
    elif len(new) < MIN_PASSWORD_LENGTH:
        flash(f"La nueva contrasena debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.", "error")
    elif new != confirm:
        flash("Las contrasenas nuevas no coinciden.", "error")
    else:
        user.set_password(new)
        db.session.commit()
        flash("Contrasena actualizada.", "success")
    return redirect(url_for("auth.profile"))
