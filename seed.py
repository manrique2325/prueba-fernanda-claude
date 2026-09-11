"""Carga de datos de demostracion.

Uso:
    python seed.py            # crea las tablas y carga los datos si la base esta vacia
    python seed.py --reset    # BORRA todo y vuelve a generar el catalogo completo

Tambien disponible como comando de Flask:  flask seed --reset
"""
from __future__ import annotations

import argparse
import random
from datetime import timedelta

from app import create_app
from app.extensions import db
from app.helpers import unique_slug
from app.models import Category, Order, OrderItem, Product, User, utcnow
from app.product_images import generate_category_image, generate_product_image
from seed_data import CATEGORIES, PRODUCTS

# --------------------------------------------------------------------------- #
# Cuentas de prueba. CAMBIAR ANTES DE PUBLICAR EL SITIO.
# --------------------------------------------------------------------------- #
ADMIN_ACCOUNT = {
    "name": "Ana Ramirez",
    "email": "admin@brillante.com",
    "password": "Admin.2026!",
    "role": "admin",
    "phone": "+54 11 5555-0142",
}

CUSTOMER_ACCOUNTS = [
    {
        "name": "Lucia Fernandez",
        "email": "cliente@brillante.com",
        "password": "Cliente.2026!",
        "role": "customer",
        "phone": "+54 11 4444-0198",
    },
    {
        "name": "Martin Diaz",
        "email": "martin@example.com",
        "password": "Cliente.2026!",
        "role": "customer",
        "phone": "+54 11 4444-0177",
    },
]

RNG = random.Random(20260910)  # semilla fija: el catalogo se regenera identico


# --------------------------------------------------------------------------- #
def reset_database() -> None:
    db.drop_all()
    db.create_all()
    print("Base de datos recreada.")


def seed_categories() -> dict[str, Category]:
    created = {}
    for position, (slug, name, icon, description) in enumerate(CATEGORIES):
        category = Category.query.filter_by(slug=slug).first()
        if category is None:
            category = Category(slug=slug, name=name)
            db.session.add(category)
        category.name = name
        category.icon = icon
        category.description = description
        category.position = position
        db.session.flush()
        category.image = generate_category_image(category, overwrite=True)
        created[slug] = category
    db.session.commit()
    print(f"{len(created)} categorias cargadas.")
    return created


def _build_description(name: str, brand: str, category_name: str, unit: str, claim: str) -> str:
    """Descripcion larga armada a partir del claim especifico de cada producto."""
    extras = [
        "Producto de la linea {brand}, con control de calidad en cada lote.",
        "Formulado en Argentina bajo normas de calidad IRAM.",
        "Envase reciclable: separalo una vez terminado el contenido.",
        "Mantener fuera del alcance de los ninos y de las mascotas.",
        "Conservar en un lugar fresco, seco y lejos de la luz directa.",
    ]
    extra = RNG.choice(extras).format(brand=brand)
    return (
        f"{name} de {brand}. {claim} "
        f"Presentacion de {unit}, pensada para uso en {category_name.lower()}. {extra}"
    )


def seed_products(categories: dict[str, Category]) -> int:
    counter = 0
    now = utcnow()
    # Resolvemos los ids una sola vez: acceder a category.id dentro del bucle
    # despertaria un refresh con autoflush sobre productos a medio construir.
    category_ids = {slug: category.id for slug, category in categories.items()}
    category_names = {slug: category.name for slug, category in categories.items()}

    for category_slug, items in PRODUCTS.items():
        for index, (name, brand, subcategory, unit, price, claim) in enumerate(items):
            counter += 1
            sku = f"{brand[:3].upper()}-{category_slug[:3].upper()}-{counter:04d}"

            product = Product.query.filter_by(sku=sku).first()
            if product is None:
                product = Product(sku=sku)
                db.session.add(product)

            product.name = name
            product.slug = unique_slug(Product, f"{name}-{brand}", exclude_id=product.id)
            product.brand = brand
            product.category_id = category_ids[category_slug]
            product.subcategory = subcategory
            product.unit = unit
            product.description = _build_description(
                name, brand, category_names[category_slug], unit, claim
            )
            product.active = True

            # --- Precio, oferta y descuento ---------------------------------
            product.price = float(price)
            if RNG.random() < 0.28:  # ~28% del catalogo en oferta
                discount = RNG.choice([10, 15, 20, 25, 30, 35, 40])
                old_price = round(price / (1 - discount / 100), -1)
                product.old_price = float(old_price)
                product.discount = int(round((1 - price / old_price) * 100))
                product.on_sale = True
            else:
                product.old_price = None
                product.discount = 0
                product.on_sale = False

            # --- Stock: la mayoria disponible, algunos escasos o agotados ----
            roll = RNG.random()
            if roll < 0.05:
                product.stock = 0
            elif roll < 0.16:
                product.stock = RNG.randint(1, 5)
            else:
                product.stock = RNG.randint(12, 120)

            product.featured = index < 2 or RNG.random() < 0.10
            product.created_at = now - timedelta(days=RNG.randint(0, 120), hours=RNG.randint(0, 23))
            db.session.flush()
            product.image = generate_product_image(product, overwrite=True)

    db.session.commit()
    print(f"{counter} productos cargados (con imagen SVG generada).")
    return counter


def seed_users() -> User:
    admin = None
    for data in [ADMIN_ACCOUNT, *CUSTOMER_ACCOUNTS]:
        user = User.query.filter_by(email=data["email"]).first()
        if user is None:
            user = User(email=data["email"])
            db.session.add(user)
        user.name = data["name"]
        user.role = data["role"]
        user.phone = data["phone"]
        user.set_password(data["password"])
        if data["role"] == "admin":
            admin = user
    db.session.commit()
    print(f"{1 + len(CUSTOMER_ACCOUNTS)} usuarios de prueba cargados.")
    return admin


def seed_demo_orders() -> int:
    """Pedidos de ejemplo para que el dashboard del admin no arranque vacio."""
    if Order.query.count():
        return 0

    customers = User.query.filter_by(role="customer").all()
    if not customers:
        return 0

    catalog = Product.query.filter(Product.stock > 5).all()
    statuses = ["entregado", "entregado", "enviado", "preparando", "confirmado", "pendiente", "cancelado"]
    created = 0

    for i in range(14):
        customer = RNG.choice(customers)
        chosen = RNG.sample(catalog, RNG.randint(2, 5))
        created_at = utcnow() - timedelta(days=RNG.randint(0, 13), hours=RNG.randint(0, 23))

        order = Order(
            number=f"BRI-{created_at.strftime('%Y%m%d')}-{2000 + i}",
            user_id=customer.id,
            status=RNG.choice(statuses),
            customer_name=customer.name,
            customer_email=customer.email,
            customer_phone=customer.phone,
            address_street="Av. Corrientes",
            address_number=str(RNG.randint(100, 4900)),
            address_city="Ciudad Autonoma de Buenos Aires",
            address_state="CABA",
            address_zip=f"C{RNG.randint(1000, 1999)}ABC",
            payment_method=RNG.choice(["transferencia", "tarjeta", "efectivo"]),
            created_at=created_at,
            subtotal=0,
            total=0,
        )
        db.session.add(order)
        db.session.flush()

        subtotal = products_total = 0.0
        for product in chosen:
            quantity = RNG.randint(1, 3)
            list_price = product.old_price or product.price
            db.session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    product_name=product.name,
                    product_sku=product.sku,
                    product_image=product.image,
                    quantity=quantity,
                    price=product.price,
                    list_price=list_price,
                )
            )
            subtotal += list_price * quantity
            products_total += product.price * quantity
            if order.status != "cancelado":
                product.stock = max(0, product.stock - quantity)

        shipping = 0.0 if products_total >= 25000 else 2900.0
        order.subtotal = round(subtotal, 2)
        order.discount = round(subtotal - products_total, 2)
        order.shipping = shipping
        order.total = round(products_total + shipping, 2)
        created += 1

    db.session.commit()
    print(f"{created} pedidos de ejemplo generados.")
    return created


def run_seed(reset: bool = False) -> None:
    app = create_app()
    with app.app_context():
        if reset:
            reset_database()
        else:
            db.create_all()

        categories = seed_categories()
        seed_products(categories)
        seed_users()
        seed_demo_orders()

        print("\n" + "=" * 62)
        print("  Datos de demostracion listos")
        print("=" * 62)
        print(f"  Categorias : {Category.query.count()}")
        print(f"  Productos  : {Product.query.count()}")
        print(f"  Usuarios   : {User.query.count()}")
        print(f"  Pedidos    : {Order.query.count()}")
        print("-" * 62)
        print("  CUENTAS DE PRUEBA (cambiar antes de publicar)")
        print(f"  Admin   : {ADMIN_ACCOUNT['email']} / {ADMIN_ACCOUNT['password']}")
        print(f"  Cliente : {CUSTOMER_ACCOUNTS[0]['email']} / {CUSTOMER_ACCOUNTS[0]['password']}")
        print("=" * 62 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga datos de demostracion en la tienda.")
    parser.add_argument("--reset", action="store_true", help="Borra la base antes de cargar.")
    run_seed(reset=parser.parse_args().reset)
