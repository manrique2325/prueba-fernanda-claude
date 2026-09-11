"""Logica de negocio: carrito, checkout y consultas del catalogo.

Se mantiene fuera de las rutas para que los blueprints queden delgados y esta
logica sea reutilizable y testeable.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from flask import current_app, session
from sqlalchemy import func, or_, select

from .extensions import db
from .models import Cart, CartItem, Order, OrderItem, Product, utcnow

GUEST_CART_KEY = "guest_cart_token"


class CartError(Exception):
    """Error de negocio del carrito, con mensaje apto para mostrar al usuario."""


# --------------------------------------------------------------------------- #
# Resolucion del carrito
# --------------------------------------------------------------------------- #
def _guest_token(create: bool = False) -> str | None:
    token = session.get(GUEST_CART_KEY)
    if not token and create:
        token = secrets.token_hex(16)
        session[GUEST_CART_KEY] = token
        session.permanent = True
    return token


def get_cart(user, create: bool = False) -> Cart | None:
    """Devuelve el carrito activo del usuario logueado o del visitante."""
    if user is not None:
        cart = Cart.query.filter_by(user_id=user.id).order_by(Cart.id.desc()).first()
        if cart is None and create:
            cart = Cart(user_id=user.id)
            db.session.add(cart)
            db.session.commit()
        return cart

    token = _guest_token(create=create)
    if not token:
        return None
    cart = Cart.query.filter_by(session_token=token, user_id=None).first()
    if cart is None and create:
        cart = Cart(session_token=token)
        db.session.add(cart)
        db.session.commit()
    return cart


def merge_guest_cart(user) -> None:
    """Fusiona el carrito anonimo con el del usuario al iniciar sesion."""
    token = session.get(GUEST_CART_KEY)
    if not token:
        return
    guest = Cart.query.filter_by(session_token=token, user_id=None).first()
    session.pop(GUEST_CART_KEY, None)
    if guest is None:
        return

    user_cart = get_cart(user, create=True)
    if user_cart.id == guest.id:  # defensivo
        return

    for item in list(guest.items):
        existing = user_cart.find_item(item.product_id)
        limit = item.product.stock
        if existing:
            existing.quantity = max(1, min(existing.quantity + item.quantity, limit))
        elif limit > 0:
            db.session.add(
                CartItem(
                    cart_id=user_cart.id,
                    product_id=item.product_id,
                    quantity=min(item.quantity, limit),
                )
            )
    db.session.delete(guest)
    db.session.commit()


# --------------------------------------------------------------------------- #
# Operaciones del carrito
# --------------------------------------------------------------------------- #
def add_to_cart(user, product_id: int, quantity: int = 1) -> CartItem:
    product = Product.query.filter_by(id=product_id, active=True).first()
    if product is None:
        raise CartError("El producto no existe o no esta disponible.")
    if product.stock <= 0:
        raise CartError(f"{product.name} esta sin stock.")

    quantity = max(1, min(int(quantity), product.stock))
    cart = get_cart(user, create=True)
    item = cart.find_item(product.id)

    if item is None:
        item = CartItem(cart_id=cart.id, product_id=product.id, quantity=quantity)
        db.session.add(item)
    else:
        new_qty = item.quantity + quantity
        if new_qty > product.stock:
            item.quantity = product.stock
            cart.updated_at = utcnow()
            db.session.commit()
            raise CartError(
                f"Solo quedan {product.stock} unidades de {product.name}; "
                "ajustamos la cantidad al maximo disponible."
            )
        item.quantity = new_qty

    cart.updated_at = utcnow()
    db.session.commit()
    return item


def set_quantity(user, product_id: int, quantity: int) -> Cart:
    cart = get_cart(user)
    if cart is None:
        raise CartError("Tu carrito esta vacio.")
    item = cart.find_item(product_id)
    if item is None:
        raise CartError("Ese producto no esta en tu carrito.")

    quantity = int(quantity)
    if quantity <= 0:
        db.session.delete(item)
    else:
        stock = item.product.stock
        if quantity > stock:
            item.quantity = max(stock, 0)
            cart.updated_at = utcnow()
            db.session.commit()
            if stock == 0:
                db.session.delete(item)
                db.session.commit()
                raise CartError(f"{item.product.name} se quedo sin stock y lo quitamos del carrito.")
            raise CartError(f"Solo hay {stock} unidades disponibles.")
        item.quantity = quantity

    cart.updated_at = utcnow()
    db.session.commit()
    return cart


def remove_from_cart(user, product_id: int) -> Cart:
    cart = get_cart(user)
    if cart is None:
        raise CartError("Tu carrito esta vacio.")
    item = cart.find_item(product_id)
    if item is not None:
        db.session.delete(item)
        cart.updated_at = utcnow()
        db.session.commit()
    return cart


def clear_cart(user) -> None:
    cart = get_cart(user)
    if cart is None:
        return
    for item in list(cart.items):
        db.session.delete(item)
    db.session.commit()


def cart_summary(cart: Cart | None) -> dict:
    """Totales calculados en el servidor (nunca se confia en el navegador)."""
    if cart is None or not cart.items:
        return {
            "units": 0,
            "subtotal": 0.0,
            "discount": 0.0,
            "shipping": 0.0,
            "total": 0.0,
            "products_total": 0.0,
            "free_shipping": False,
            "missing_for_free": current_app.config["FREE_SHIPPING_THRESHOLD"],
        }

    products_total = cart.total
    threshold = current_app.config["FREE_SHIPPING_THRESHOLD"]
    shipping = 0.0 if products_total >= threshold else current_app.config["SHIPPING_COST"]
    return {
        "units": cart.total_units,
        "subtotal": cart.subtotal,
        "discount": cart.discount_total,
        "shipping": shipping,
        "total": round(products_total + shipping, 2),
        "products_total": products_total,
        "free_shipping": shipping == 0,
        "missing_for_free": max(0.0, round(threshold - products_total, 2)),
    }


def validate_cart_stock(cart: Cart) -> list[str]:
    """Ajusta el carrito al stock real y devuelve los avisos generados."""
    problems: list[str] = []
    for item in list(cart.items):
        product = item.product
        if product is None or not product.active:
            problems.append("Quitamos un producto que ya no esta disponible.")
            db.session.delete(item)
        elif product.stock <= 0:
            problems.append(f"{product.name} se quedo sin stock y lo quitamos del carrito.")
            db.session.delete(item)
        elif item.quantity > product.stock:
            problems.append(f"Ajustamos {product.name} a {product.stock} unidades (stock disponible).")
            item.quantity = product.stock
    if problems:
        db.session.commit()
    return problems


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def generate_order_number() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(10):
        number = f"BRI-{stamp}-{secrets.randbelow(9000) + 1000}"
        if not Order.query.filter_by(number=number).first():
            return number
    return f"BRI-{stamp}-{secrets.token_hex(3).upper()}"


def create_order(user, cart: Cart, form: dict) -> Order:
    """Crea el pedido, descuenta stock y vacia el carrito, todo en una transaccion."""
    if not cart or not cart.items:
        raise CartError("Tu carrito esta vacio.")

    problems = validate_cart_stock(cart)
    if problems:
        raise CartError(" ".join(problems))
    if not cart.items:
        raise CartError("Tu carrito quedo vacio por falta de stock.")

    totals = cart_summary(cart)
    order = Order(
        number=generate_order_number(),
        user_id=user.id,
        status="pendiente",
        subtotal=totals["subtotal"],
        discount=totals["discount"],
        shipping=totals["shipping"],
        total=totals["total"],
        customer_name=form["customer_name"],
        customer_email=form["customer_email"],
        customer_phone=form.get("customer_phone"),
        address_street=form.get("address_street"),
        address_number=form.get("address_number"),
        address_city=form.get("address_city"),
        address_state=form.get("address_state"),
        address_zip=form.get("address_zip"),
        payment_method=form.get("payment_method"),
        notes=form.get("notes"),
    )
    db.session.add(order)
    db.session.flush()  # necesitamos order.id

    for item in cart.items:
        product = item.product
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                product_image=product.image,
                quantity=item.quantity,
                price=product.price,
                list_price=product.old_price or product.price,
            )
        )
        product.stock = max(0, product.stock - item.quantity)  # descuento de stock
        db.session.delete(item)

    db.session.commit()
    return order


# --------------------------------------------------------------------------- #
# Catalogo: busqueda, filtros, orden y paginacion
# --------------------------------------------------------------------------- #
SORT_OPTIONS = {
    "relevancia": "Relevancia",
    "precio_asc": "Precio: menor a mayor",
    "precio_desc": "Precio: mayor a menor",
    "nuevos": "Mas nuevos",
    "ofertas": "Mejores ofertas",
    "nombre": "Nombre (A-Z)",
}


def build_product_query(args):
    """Construye la consulta del catalogo a partir de los parametros de la URL.

    Devuelve (statement, filtros_normalizados) usando la API select() de
    SQLAlchemy 2.0, que es lo que espera db.paginate(). Todos los filtros
    consultan la base de datos; ninguno se resuelve en el cliente.
    """
    from .models import Category  # import local para evitar ciclos

    query = select(Product).where(Product.active.is_(True))

    def _clean(name):
        value = (args.get(name) or "").strip()
        return value or None

    filters = {
        "q": _clean("q"),
        "categoria": _clean("categoria"),
        "marca": args.getlist("marca") if hasattr(args, "getlist") else [],
        "subcategoria": _clean("subcategoria"),
        "min": args.get("min", type=float),
        "max": args.get("max", type=float),
        "oferta": args.get("oferta") in {"1", "true", "on"},
        "stock": args.get("stock") in {"1", "true", "on"},
        "orden": args.get("orden") if args.get("orden") in SORT_OPTIONS else "relevancia",
    }
    filters["marca"] = [m for m in filters["marca"] if m.strip()]

    if filters["q"]:
        like = f"%{filters['q']}%"
        query = query.join(Category, Product.category_id == Category.id).where(
            or_(
                Product.name.ilike(like),
                Product.brand.ilike(like),
                Product.sku.ilike(like),
                Product.subcategory.ilike(like),
                Product.description.ilike(like),
                Category.name.ilike(like),
            )
        )

    if filters["categoria"]:
        query = query.where(
            Product.category_id.in_(select(Category.id).where(Category.slug == filters["categoria"]))
        )
    if filters["subcategoria"]:
        query = query.where(Product.subcategory == filters["subcategoria"])
    if filters["marca"]:
        query = query.where(Product.brand.in_(filters["marca"]))
    if filters["min"] is not None:
        query = query.where(Product.price >= filters["min"])
    if filters["max"] is not None:
        query = query.where(Product.price <= filters["max"])
    if filters["oferta"]:
        query = query.where(Product.on_sale.is_(True))
    if filters["stock"]:
        query = query.where(Product.stock > 0)

    orden = filters["orden"]
    if orden == "precio_asc":
        query = query.order_by(Product.price.asc())
    elif orden == "precio_desc":
        query = query.order_by(Product.price.desc())
    elif orden == "nuevos":
        query = query.order_by(Product.created_at.desc(), Product.id.desc())
    elif orden == "ofertas":
        query = query.order_by(Product.discount.desc(), Product.price.asc())
    elif orden == "nombre":
        query = query.order_by(Product.name.asc())
    else:  # relevancia: destacados y con stock primero
        query = query.order_by(
            (Product.stock > 0).desc(), Product.featured.desc(), Product.discount.desc(), Product.id.asc()
        )

    return query, filters


def available_brands(category_slug: str | None = None) -> list[str]:
    from .models import Category

    q = db.session.query(Product.brand).filter(Product.active.is_(True))
    if category_slug:
        q = q.join(Category, Product.category_id == Category.id).filter(Category.slug == category_slug)
    return sorted({row[0] for row in q.distinct().all()})


def price_bounds() -> tuple[float, float]:
    row = db.session.query(func.min(Product.price), func.max(Product.price)).filter(
        Product.active.is_(True)
    ).one()
    return (row[0] or 0.0, row[1] or 0.0)


def related_products(product: Product, limit: int = 5) -> list[Product]:
    """Productos de la misma subcategoria; completa con la categoria si faltan."""
    base = Product.query.filter(
        Product.active.is_(True), Product.id != product.id, Product.category_id == product.category_id
    )
    items = base.filter(Product.subcategory == product.subcategory).order_by(func.random()).limit(limit).all()
    if len(items) < limit:
        exclude = [product.id] + [p.id for p in items]
        extra = (
            base.filter(~Product.id.in_(exclude))
            .order_by(func.random())
            .limit(limit - len(items))
            .all()
        )
        items.extend(extra)
    return items
