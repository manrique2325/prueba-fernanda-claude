"""Application factory."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, g, render_template, request

from config import Config
from .extensions import db


def create_app(config_object: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)

    # Carpeta instance/ para el archivo SQLite
    Path(app.root_path).parent.joinpath("instance").mkdir(exist_ok=True)

    db.init_app(app)

    _register_blueprints(app)
    _register_hooks(app)
    _register_template_helpers(app)
    _register_error_handlers(app)
    _register_cli(app)
    return app


def _register_blueprints(app: Flask) -> None:
    from .blueprints.admin import bp as admin_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.cart import bp as cart_bp
    from .blueprints.main import bp as main_bp
    from .blueprints.orders import bp as orders_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(cart_bp, url_prefix="/carrito")
    app.register_blueprint(orders_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")


def _register_hooks(app: Flask) -> None:
    from .helpers import load_current_user
    from .services import cart_summary, get_cart

    @app.before_request
    def _before():
        load_current_user()

    @app.context_processor
    def _inject_globals():
        from .models import Category

        user = getattr(g, "user", None)
        cart = get_cart(user)
        return {
            "current_user": user,
            "cart": cart,
            "cart_summary": cart_summary(cart),
            "nav_categories": Category.query.order_by(Category.position, Category.name).all(),
            "store": {
                "name": app.config["STORE_NAME"],
                "tagline": app.config["STORE_TAGLINE"],
                "email": app.config["STORE_EMAIL"],
                "phone": app.config["STORE_PHONE"],
                "address": app.config["STORE_ADDRESS"],
                "free_shipping": app.config["FREE_SHIPPING_THRESHOLD"],
                "shipping_cost": app.config["SHIPPING_COST"],
            },
            "request_args": request.args,
            "now_year": datetime.now().year,
        }


def _register_template_helpers(app: Flask) -> None:
    from .helpers import format_price
    from .services import SORT_OPTIONS

    app.add_template_filter(format_price, "price")
    app.jinja_env.globals["SORT_OPTIONS"] = SORT_OPTIONS

    @app.template_global()
    def url_with(**changes):
        """URL actual cambiando/quitando parametros (paginacion y filtros)."""
        from flask import url_for

        params = dict(request.view_args or {})
        params.update(request.args.to_dict(flat=False))
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        return url_for(request.endpoint, **params)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def _404(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def _403(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def _500(error):
        db.session.rollback()
        app.logger.exception("Error interno: %s", error)
        return render_template("errors/500.html"), 500


def _register_cli(app: Flask) -> None:
    import click

    @app.cli.command("init-db")
    def init_db():
        """Crea las tablas (sin datos)."""
        db.create_all()
        click.echo("Tablas creadas.")

    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Borra la base antes de cargar los datos.")
    def seed_command(reset):
        """Carga categorias, productos y usuarios de prueba."""
        from seed import run_seed

        run_seed(reset=reset)
