"""Panel de administracion: dashboard, productos, categorias, pedidos y usuarios.

Todas las rutas estan protegidas por @admin_required (ver helpers.py).
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from ..extensions import db
from ..helpers import admin_required, parse_float, parse_int, unique_slug
from ..models import (
    ORDER_STATUSES,
    Category,
    Order,
    OrderItem,
    Product,
    User,
    utcnow,
)
from ..product_images import generate_product_image
from ..services import available_brands

bp = Blueprint("admin", __name__)

LOW_STOCK_THRESHOLD = 8


@bp.before_request
@admin_required
def _guard():
    """Protege todo el blueprint de una sola vez."""
    return None


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@bp.route("/")
def dashboard():
    paid_orders = Order.query.filter(Order.status != "cancelado")
    revenue = db.session.query(func.coalesce(func.sum(Order.total), 0.0)).filter(
        Order.status != "cancelado"
    ).scalar()

    stats = {
        "revenue": round(revenue or 0, 2),
        "orders": Order.query.count(),
        "pending": Order.query.filter_by(status="pendiente").count(),
        "users": User.query.filter_by(role="customer").count(),
        "products": Product.query.filter_by(active=True).count(),
        "out_of_stock": Product.query.filter(Product.stock == 0, Product.active.is_(True)).count(),
        "avg_ticket": round((revenue or 0) / max(paid_orders.count(), 1), 2),
    }

    low_stock = (
        Product.query.filter(Product.active.is_(True), Product.stock <= LOW_STOCK_THRESHOLD)
        .order_by(Product.stock.asc())
        .limit(10)
        .all()
    )
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()

    # Ventas de los ultimos 14 dias (para el grafico del dashboard)
    since = utcnow() - timedelta(days=13)
    sales_by_day = {}
    for order in Order.query.filter(Order.created_at >= since, Order.status != "cancelado").all():
        key = order.created_at.strftime("%d/%m")
        sales_by_day[key] = sales_by_day.get(key, 0) + order.total
    chart_days = [(since + timedelta(days=i)).strftime("%d/%m") for i in range(14)]
    chart = [{"label": d, "value": round(sales_by_day.get(d, 0), 2)} for d in chart_days]

    top_products = (
        db.session.query(
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("units"),
            func.sum(OrderItem.quantity * OrderItem.price).label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != "cancelado")
        .group_by(OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(6)
        .all()
    )

    status_counts = dict(
        db.session.query(Order.status, func.count(Order.id)).group_by(Order.status).all()
    )

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        low_stock=low_stock,
        recent_orders=recent_orders,
        chart=chart,
        top_products=top_products,
        status_counts=status_counts,
        statuses=ORDER_STATUSES,
    )


# --------------------------------------------------------------------------- #
# Productos
# --------------------------------------------------------------------------- #
@bp.route("/productos")
def products():
    query = select(Product)
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        query = query.where(
            or_(Product.name.ilike(like), Product.brand.ilike(like), Product.sku.ilike(like))
        )
    category_id = request.args.get("categoria", type=int)
    if category_id:
        query = query.where(Product.category_id == category_id)
    if request.args.get("stock") == "bajo":
        query = query.where(Product.stock <= LOW_STOCK_THRESHOLD)
    if request.args.get("estado") == "inactivos":
        query = query.where(Product.active.is_(False))

    pagination = db.paginate(
        query.order_by(Product.id.desc()), page=request.args.get("page", 1, type=int), per_page=20, error_out=False
    )
    return render_template(
        "admin/products.html",
        pagination=pagination,
        products=pagination.items,
        categories=Category.query.order_by(Category.name).all(),
        term=term,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
    )


def _product_form_data(form) -> tuple[dict, list[str]]:
    data = {
        "name": (form.get("name") or "").strip(),
        "brand": (form.get("brand") or "").strip(),
        "category_id": parse_int(form.get("category_id"), default=0),
        "subcategory": (form.get("subcategory") or "").strip() or None,
        "description": (form.get("description") or "").strip(),
        "price": parse_float(form.get("price"), default=0, minimum=0),
        "old_price": parse_float(form.get("old_price"), default=0, minimum=0) or None,
        "stock": parse_int(form.get("stock"), default=0, minimum=0),
        "sku": (form.get("sku") or "").strip().upper(),
        "unit": (form.get("unit") or "").strip() or None,
        "image": (form.get("image") or "").strip() or None,
        "featured": form.get("featured") == "on",
        "on_sale": form.get("on_sale") == "on",
        "active": form.get("active") == "on",
    }

    errors = []
    if len(data["name"]) < 3:
        errors.append("El nombre debe tener al menos 3 caracteres.")
    if not data["brand"]:
        errors.append("La marca es obligatoria.")
    if not db.session.get(Category, data["category_id"]):
        errors.append("Selecciona una categoria valida.")
    if data["price"] <= 0:
        errors.append("El precio debe ser mayor a cero.")
    if data["old_price"] and data["old_price"] <= data["price"]:
        errors.append("El precio anterior debe ser mayor al precio actual.")
    if len(data["description"]) < 10:
        errors.append("La descripcion debe tener al menos 10 caracteres.")
    return data, errors


def _apply_pricing(product: Product) -> None:
    """Recalcula descuento y bandera de oferta a partir de los precios."""
    if product.old_price and product.old_price > product.price:
        product.discount = int(round((1 - product.price / product.old_price) * 100))
        product.on_sale = True
    else:
        product.old_price = None
        product.discount = 0
        product.on_sale = False


@bp.route("/productos/nuevo", methods=["GET", "POST"])
def product_new():
    if request.method == "POST":
        data, errors = _product_form_data(request.form)
        if data["sku"] and Product.query.filter_by(sku=data["sku"]).first():
            errors.append("Ya existe un producto con ese SKU.")
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "admin/product_form.html",
                    product=None,
                    form=data,
                    categories=Category.query.order_by(Category.name).all(),
                    brands=available_brands(),
                ),
                400,
            )

        product = Product(**{k: v for k, v in data.items() if k not in {"on_sale"}})
        product.slug = unique_slug(Product, data["name"])
        if not product.sku:
            product.sku = f"BRI-{Product.query.count() + 1:05d}"
        if not product.image:
            product.image = generate_product_image(product)
        _apply_pricing(product)
        db.session.add(product)
        db.session.commit()
        flash(f"Producto \"{product.name}\" creado.", "success")
        return redirect(url_for("admin.products"))

    return render_template(
        "admin/product_form.html",
        product=None,
        form={"active": True, "stock": 0},
        categories=Category.query.order_by(Category.name).all(),
        brands=available_brands(),
    )


@bp.route("/productos/<int:product_id>/editar", methods=["GET", "POST"])
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)

    if request.method == "POST":
        data, errors = _product_form_data(request.form)
        if data["sku"] and Product.query.filter(
            Product.sku == data["sku"], Product.id != product.id
        ).first():
            errors.append("Ya existe otro producto con ese SKU.")
        if errors:
            for error in errors:
                flash(error, "error")
            return (
                render_template(
                    "admin/product_form.html",
                    product=product,
                    form=data,
                    categories=Category.query.order_by(Category.name).all(),
                    brands=available_brands(),
                ),
                400,
            )

        name_changed = data["name"] != product.name
        for key, value in data.items():
            if key == "on_sale":
                continue
            setattr(product, key, value)
        if name_changed:
            product.slug = unique_slug(Product, data["name"], exclude_id=product.id)
        if not product.image:
            product.image = generate_product_image(product)
        _apply_pricing(product)
        db.session.commit()
        flash("Producto actualizado.", "success")
        return redirect(url_for("admin.products"))

    form = {
        "name": product.name,
        "brand": product.brand,
        "category_id": product.category_id,
        "subcategory": product.subcategory or "",
        "description": product.description,
        "price": product.price,
        "old_price": product.old_price or "",
        "stock": product.stock,
        "sku": product.sku,
        "unit": product.unit or "",
        "image": product.image or "",
        "featured": product.featured,
        "on_sale": product.on_sale,
        "active": product.active,
    }
    return render_template(
        "admin/product_form.html",
        product=product,
        form=form,
        categories=Category.query.order_by(Category.name).all(),
        brands=available_brands(),
    )


@bp.route("/productos/<int:product_id>/stock", methods=["POST"])
def product_stock(product_id):
    """Edicion rapida de stock desde el listado."""
    product = Product.query.get_or_404(product_id)
    product.stock = parse_int(request.form.get("stock"), default=product.stock, minimum=0)
    db.session.commit()
    flash(f"Stock de {product.name}: {product.stock} unidades.", "success")
    return redirect(request.referrer or url_for("admin.products"))


@bp.route("/productos/<int:product_id>/eliminar", methods=["POST"])
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    name = product.name
    sold = OrderItem.query.filter_by(product_id=product.id).count()

    if sold:
        # Baja logica: preserva el historial de pedidos.
        product.active = False
        product.featured = False
        db.session.commit()
        flash(
            f"\"{name}\" tiene ventas asociadas: se desactivo en lugar de borrarse "
            "para no romper el historial de pedidos.",
            "info",
        )
    else:
        db.session.delete(product)
        db.session.commit()
        flash(f"Producto \"{name}\" eliminado.", "success")
    return redirect(url_for("admin.products"))


@bp.route("/productos/<int:product_id>/destacar", methods=["POST"])
def product_toggle_featured(product_id):
    product = Product.query.get_or_404(product_id)
    product.featured = not product.featured
    db.session.commit()
    flash(
        f"{product.name} {'agregado a' if product.featured else 'quitado de'} destacados.", "success"
    )
    return redirect(request.referrer or url_for("admin.products"))


# --------------------------------------------------------------------------- #
# Categorias
# --------------------------------------------------------------------------- #
@bp.route("/categorias", methods=["GET", "POST"])
def categories():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if len(name) < 3:
            flash("El nombre de la categoria debe tener al menos 3 caracteres.", "error")
        elif Category.query.filter(func.lower(Category.name) == name.lower()).first():
            flash("Ya existe una categoria con ese nombre.", "error")
        else:
            category = Category(
                name=name,
                slug=unique_slug(Category, name),
                description=(request.form.get("description") or "").strip(),
                icon=(request.form.get("icon") or "").strip()[:8],
                position=parse_int(request.form.get("position"), default=99),
            )
            from ..product_images import generate_category_image

            category.image = generate_category_image(category)
            db.session.add(category)
            db.session.commit()
            flash(f"Categoria \"{name}\" creada.", "success")
        return redirect(url_for("admin.categories"))

    return render_template(
        "admin/categories.html",
        categories=Category.query.order_by(Category.position, Category.name).all(),
    )


@bp.route("/categorias/<int:category_id>/editar", methods=["POST"])
def category_edit(category_id):
    category = Category.query.get_or_404(category_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 3:
        flash("El nombre debe tener al menos 3 caracteres.", "error")
        return redirect(url_for("admin.categories"))

    duplicate = Category.query.filter(
        func.lower(Category.name) == name.lower(), Category.id != category.id
    ).first()
    if duplicate:
        flash("Ya existe otra categoria con ese nombre.", "error")
        return redirect(url_for("admin.categories"))

    if name != category.name:
        category.slug = unique_slug(Category, name, exclude_id=category.id)
    category.name = name
    category.description = (request.form.get("description") or "").strip()
    category.icon = (request.form.get("icon") or "").strip()[:8]
    category.position = parse_int(request.form.get("position"), default=category.position)
    db.session.commit()
    flash("Categoria actualizada.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categorias/<int:category_id>/eliminar", methods=["POST"])
def category_delete(category_id):
    category = Category.query.get_or_404(category_id)
    if category.products:
        flash(
            f"No se puede eliminar \"{category.name}\": tiene {len(category.products)} productos. "
            "Movelos a otra categoria primero.",
            "error",
        )
    else:
        db.session.delete(category)
        db.session.commit()
        flash("Categoria eliminada.", "success")
    return redirect(url_for("admin.categories"))


# --------------------------------------------------------------------------- #
# Pedidos
# --------------------------------------------------------------------------- #
@bp.route("/pedidos")
def orders():
    query = select(Order)
    status = request.args.get("estado")
    if status in ORDER_STATUSES:
        query = query.where(Order.status == status)
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        query = query.where(
            or_(
                Order.number.ilike(like),
                Order.customer_name.ilike(like),
                Order.customer_email.ilike(like),
            )
        )

    pagination = db.paginate(
        query.order_by(Order.created_at.desc()),
        page=request.args.get("page", 1, type=int),
        per_page=20,
        error_out=False,
    )
    return render_template(
        "admin/orders.html",
        pagination=pagination,
        orders=pagination.items,
        statuses=ORDER_STATUSES,
        status=status,
        term=term,
    )


@bp.route("/pedidos/<int:order_id>")
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("admin/order_detail.html", order=order, statuses=ORDER_STATUSES)


@bp.route("/pedidos/<int:order_id>/estado", methods=["POST"])
def order_status(order_id):
    order = Order.query.get_or_404(order_id)
    status = request.form.get("status")
    if status not in ORDER_STATUSES:
        abort(400)

    previous = order.status
    # Al cancelar un pedido devolvemos el stock reservado.
    if status == "cancelado" and previous != "cancelado":
        for item in order.items:
            if item.product:
                item.product.stock += item.quantity
    # Reactivar un pedido cancelado vuelve a descontar el stock.
    elif previous == "cancelado" and status != "cancelado":
        for item in order.items:
            if item.product:
                item.product.stock = max(0, item.product.stock - item.quantity)

    order.status = status
    db.session.commit()
    flash(f"Pedido {order.number}: estado \"{order.status_label}\".", "success")
    return redirect(request.referrer or url_for("admin.orders"))


# --------------------------------------------------------------------------- #
# Usuarios
# --------------------------------------------------------------------------- #
@bp.route("/usuarios")
def users():
    query = select(User)
    term = (request.args.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        query = query.where(or_(User.name.ilike(like), User.email.ilike(like)))

    pagination = db.paginate(
        query.order_by(User.created_at.desc()),
        page=request.args.get("page", 1, type=int),
        per_page=20,
        error_out=False,
    )
    order_counts = dict(
        db.session.query(Order.user_id, func.count(Order.id)).group_by(Order.user_id).all()
    )
    spent = dict(
        db.session.query(Order.user_id, func.sum(Order.total))
        .filter(Order.status != "cancelado")
        .group_by(Order.user_id)
        .all()
    )
    return render_template(
        "admin/users.html",
        pagination=pagination,
        users=pagination.items,
        order_counts=order_counts,
        spent=spent,
        term=term,
    )


@bp.route("/usuarios/<int:user_id>/rol", methods=["POST"])
def user_role(user_id):
    from ..helpers import current_user

    user = User.query.get_or_404(user_id)
    role = request.form.get("role")
    if role not in {"customer", "admin"}:
        abort(400)
    if user.id == current_user().id:
        flash("No podes cambiar tu propio rol.", "error")
        return redirect(url_for("admin.users"))

    user.role = role
    db.session.commit()
    flash(f"{user.name} ahora es {'administrador' if role == 'admin' else 'cliente'}.", "success")
    return redirect(url_for("admin.users"))
