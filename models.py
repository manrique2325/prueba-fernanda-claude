"""Modelos de datos.

Convenciones:
  * Los precios se guardan como Float (suficiente para una demo). En produccion
    convendria Numeric(10, 2) para evitar errores de redondeo.
  * Todos los totales monetarios se recalculan en el servidor; nunca se confia
    en valores enviados por el navegador.
"""
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- #
# Usuarios
# --------------------------------------------------------------------------- #
class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="customer", nullable=False)  # customer | admin
    phone = db.Column(db.String(40))

    carts = db.relationship("Cart", back_populates="user", cascade="all, delete-orphan")
    orders = db.relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Order.created_at.desc()",
    )

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "U"

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #
class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    icon = db.Column(db.String(16), default="")
    position = db.Column(db.Integer, default=0)

    products = db.relationship("Product", back_populates="category")

    @property
    def product_count(self) -> int:
        return Product.query.filter_by(category_id=self.id, active=True).count()

    def __repr__(self) -> str:
        return f"<Category {self.slug}>"


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    slug = db.Column(db.String(220), unique=True, nullable=False, index=True)
    brand = db.Column(db.String(120), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    subcategory = db.Column(db.String(120), index=True)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    old_price = db.Column(db.Float)               # precio tachado (opcional)
    discount = db.Column(db.Integer, default=0)   # porcentaje entero
    image = db.Column(db.String(255))
    stock = db.Column(db.Integer, default=0, nullable=False)
    sku = db.Column(db.String(40), unique=True, nullable=False, index=True)
    featured = db.Column(db.Boolean, default=False, index=True)
    on_sale = db.Column(db.Boolean, default=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    unit = db.Column(db.String(40))               # "750 ml", "2 un.", etc.

    category = db.relationship("Category", back_populates="products")
    cart_items = db.relationship("CartItem", back_populates="product", cascade="all, delete-orphan")
    order_items = db.relationship("OrderItem", back_populates="product")

    @property
    def in_stock(self) -> bool:
        return self.stock > 0

    @property
    def low_stock(self) -> bool:
        return 0 < self.stock <= 5

    @property
    def is_new(self) -> bool:
        """Producto cargado en los ultimos 30 dias."""
        if not self.created_at:
            return False
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (utcnow() - created).days <= 30

    @property
    def savings(self) -> float:
        if self.old_price and self.old_price > self.price:
            return round(self.old_price - self.price, 2)
        return 0.0

    def __repr__(self) -> str:
        return f"<Product {self.sku} {self.name!r}>"


# --------------------------------------------------------------------------- #
# Carrito
# --------------------------------------------------------------------------- #
class Cart(TimestampMixin, db.Model):
    """Carrito persistente.

    Se asocia a un usuario (user_id) o, para visitantes, a un token guardado en
    la cookie de sesion. Al iniciar sesion el carrito anonimo se fusiona con el
    carrito de la cuenta (ver services.merge_guest_cart).
    """

    __tablename__ = "carts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    session_token = db.Column(db.String(64), index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="carts")
    items = db.relationship(
        "CartItem", back_populates="cart", cascade="all, delete-orphan", order_by="CartItem.id"
    )

    # -- totales (siempre calculados en el servidor) -----------------------
    @property
    def total_units(self) -> int:
        return sum(i.quantity for i in self.items)

    @property
    def subtotal(self) -> float:
        """Suma a precio de lista, antes de descuentos."""
        return round(sum((i.product.old_price or i.product.price) * i.quantity for i in self.items), 2)

    @property
    def total(self) -> float:
        return round(sum(i.line_total for i in self.items), 2)

    @property
    def discount_total(self) -> float:
        return round(self.subtotal - self.total, 2)

    def find_item(self, product_id: int):
        return next((i for i in self.items if i.product_id == product_id), None)

    def __repr__(self) -> str:
        return f"<Cart {self.id} user={self.user_id} items={len(self.items)}>"


class CartItem(db.Model):
    __tablename__ = "cart_items"
    __table_args__ = (db.UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),)

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("carts.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)

    cart = db.relationship("Cart", back_populates="items")
    product = db.relationship("Product", back_populates="cart_items")

    @property
    def line_total(self) -> float:
        return round(self.product.price * self.quantity, 2)


# --------------------------------------------------------------------------- #
# Pedidos
# --------------------------------------------------------------------------- #
ORDER_STATUSES = ["pendiente", "confirmado", "preparando", "enviado", "entregado", "cancelado"]

STATUS_LABELS = {
    "pendiente": "Pendiente",
    "confirmado": "Confirmado",
    "preparando": "Preparando",
    "enviado": "Enviado",
    "entregado": "Entregado",
    "cancelado": "Cancelado",
}


class Order(TimestampMixin, db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(24), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), default="pendiente", nullable=False, index=True)

    # Importes congelados al momento de la compra
    subtotal = db.Column(db.Float, nullable=False, default=0)
    discount = db.Column(db.Float, nullable=False, default=0)
    shipping = db.Column(db.Float, nullable=False, default=0)
    total = db.Column(db.Float, nullable=False, default=0)

    # Snapshot de datos del cliente / envio
    customer_name = db.Column(db.String(120), nullable=False)
    customer_email = db.Column(db.String(255), nullable=False)
    customer_phone = db.Column(db.String(40))
    address_street = db.Column(db.String(200))
    address_number = db.Column(db.String(20))
    address_city = db.Column(db.String(120))
    address_state = db.Column(db.String(120))
    address_zip = db.Column(db.String(20))
    payment_method = db.Column(db.String(40))
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.title())

    @property
    def total_units(self) -> int:
        return sum(i.quantity for i in self.items)

    @property
    def full_address(self) -> str:
        street = f"{self.address_street or ''} {self.address_number or ''}".strip()
        parts = [street, self.address_city, self.address_state, self.address_zip]
        return ", ".join(p for p in parts if p)

    def __repr__(self) -> str:
        return f"<Order {self.number} {self.status}>"


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), index=True)
    # Snapshot: el pedido debe seguir siendo legible aunque el producto cambie.
    product_name = db.Column(db.String(200), nullable=False)
    product_sku = db.Column(db.String(40))
    product_image = db.Column(db.String(255))
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)   # precio pagado por unidad
    list_price = db.Column(db.Float)              # precio de lista al comprar

    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product", back_populates="order_items")

    @property
    def line_total(self) -> float:
        return round(self.price * self.quantity, 2)
