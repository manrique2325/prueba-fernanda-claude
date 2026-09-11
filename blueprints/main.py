"""Catalogo publico: home, listado con filtros, detalle de producto y busqueda."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request
from sqlalchemy import func

from ..extensions import db
from ..models import Category, Product
from ..services import available_brands, build_product_query, price_bounds, related_products

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    featured = (
        Product.query.filter_by(featured=True, active=True)
        .filter(Product.stock > 0)
        .order_by(func.random())
        .limit(8)
        .all()
    )
    offers = (
        Product.query.filter_by(on_sale=True, active=True)
        .filter(Product.stock > 0)
        .order_by(Product.discount.desc())
        .limit(8)
        .all()
    )
    newest = (
        Product.query.filter_by(active=True)
        .order_by(Product.created_at.desc(), Product.id.desc())
        .limit(8)
        .all()
    )
    categories = Category.query.order_by(Category.position, Category.name).all()
    return render_template(
        "index.html",
        featured=featured,
        offers=offers,
        newest=newest,
        categories=categories,
    )


@bp.route("/productos")
def products():
    query, filters = build_product_query(request.args)
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config["PRODUCTS_PER_PAGE"]
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)

    category = (
        Category.query.filter_by(slug=filters["categoria"]).first() if filters["categoria"] else None
    )
    min_price, max_price = price_bounds()

    subcategories = []
    if category:
        subcategories = sorted(
            {
                row[0]
                for row in db.session.query(Product.subcategory)
                .filter(Product.category_id == category.id, Product.active.is_(True))
                .distinct()
                .all()
                if row[0]
            }
        )

    return render_template(
        "products.html",
        pagination=pagination,
        products=pagination.items,
        filters=filters,
        category=category,
        categories=Category.query.order_by(Category.position, Category.name).all(),
        brands=available_brands(filters["categoria"]),
        subcategories=subcategories,
        min_price=min_price,
        max_price=max_price,
    )


@bp.route("/categoria/<slug>")
def category(slug):
    """Atajo legible que reutiliza el listado con el filtro de categoria."""
    cat = Category.query.filter_by(slug=slug).first_or_404()
    args = request.args.to_dict(flat=False)
    args["categoria"] = [cat.slug]

    from werkzeug.datastructures import MultiDict

    query, filters = build_product_query(MultiDict(args))
    page = request.args.get("page", 1, type=int)
    pagination = db.paginate(
        query, page=page, per_page=current_app.config["PRODUCTS_PER_PAGE"], error_out=False
    )
    subcategories = sorted(
        {
            row[0]
            for row in db.session.query(Product.subcategory)
            .filter(Product.category_id == cat.id, Product.active.is_(True))
            .distinct()
            .all()
            if row[0]
        }
    )
    min_price, max_price = price_bounds()
    return render_template(
        "products.html",
        pagination=pagination,
        products=pagination.items,
        filters=filters,
        category=cat,
        categories=Category.query.order_by(Category.position, Category.name).all(),
        brands=available_brands(cat.slug),
        subcategories=subcategories,
        min_price=min_price,
        max_price=max_price,
    )


@bp.route("/producto/<int:product_id>")
def product_detail(product_id):
    product = Product.query.filter_by(id=product_id, active=True).first_or_404()
    return render_template(
        "product.html", product=product, related=related_products(product, limit=5)
    )


@bp.route("/buscar")
def search():
    """La busqueda reutiliza el listado de productos con el parametro q."""
    return products()


@bp.route("/api/sugerencias")
def suggestions():
    """Autocompletado del buscador (consulta real a la base)."""
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify({"products": [], "categories": []})

    like = f"%{term}%"
    products_found = (
        Product.query.filter(Product.active.is_(True))
        .filter(
            db.or_(
                Product.name.ilike(like),
                Product.brand.ilike(like),
                Product.sku.ilike(like),
            )
        )
        .order_by(Product.featured.desc(), Product.name)
        .limit(6)
        .all()
    )
    categories_found = Category.query.filter(Category.name.ilike(like)).limit(3).all()
    return jsonify(
        {
            "products": [
                {
                    "id": p.id,
                    "name": p.name,
                    "brand": p.brand,
                    "price": p.price,
                    "image": p.image,
                    "url": f"/producto/{p.id}",
                }
                for p in products_found
            ],
            "categories": [{"name": c.name, "url": f"/categoria/{c.slug}"} for c in categories_found],
        }
    )


@bp.route("/ayuda/envios")
def shipping_info():
    return render_template("static_page.html", page="envios")


@bp.route("/ayuda/contacto")
def contact():
    return render_template("static_page.html", page="contacto")


@bp.route("/ayuda/nosotros")
def about():
    return render_template("static_page.html", page="nosotros")
