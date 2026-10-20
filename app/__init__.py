import os

from flask import Flask, render_template

from config import config
from extensions import db, migrate


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "development")

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Fail fast on a deployment left on the dev secret: anyone could forge a
    # session cookie and sign in as an admin. `from_object` only copies class
    # attributes, so this must be checked here rather than in ProdConfig.
    if config_name == "production":
        _require_strong_secret(app)

    _ensure_instance_folder(app)
    _configure_proxy(app)

    db.init_app(app)
    migrate.init_app(app, db)

    _register_models()

    # Must come after db.init_app (models are queried) and before blueprints
    # are registered, so every request runs the auth + CSRF guards.
    from app.security import init_security

    init_security(app)

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_cli(app)
    _register_shell_context(app)
    _register_template_filters(app)

    return app


def _register_template_filters(app):
    from app.security import login_manager  # noqa: F401  (ensures security is up)

    @app.template_global("csrf_token")
    def _csrf_token():
        """Render a CSRF token for a form. Guarded so templates that render
        without a request context (error pages during teardown) don't crash."""
        try:
            from flask_wtf.csrf import generate_csrf

            return generate_csrf()
        except RuntimeError:
            return ""

    @app.template_global("currency_symbol")
    def currency_symbol():
        """The configured money symbol (default '$'), for places where a bare
        symbol reads better than a full formatted amount (e.g. "$/km")."""
        return app.config.get("CURRENCY_SYMBOL", "$")

    @app.template_filter("currency")
    def currency(value):
        """Format a money value with the configured symbol, e.g. $1,234.50."""
        try:
            amount = float(value or 0)
        except (TypeError, ValueError):
            amount = 0.0
        symbol = app.config.get("CURRENCY_SYMBOL", "$")
        return f"{symbol}{amount:,.2f}"

    @app.template_filter("trip_status")
    def trip_status(value):
        """Render a trip status in Somali, e.g. 'in_progress' -> 'baxay'.

        Display-only: the stored value stays the English enum, which is what
        filtering and the badge CSS classes key off. Unknown values pass
        through unchanged rather than rendering blank.
        """
        from app.models.trip import TRIP_STATUS_LABELS

        return TRIP_STATUS_LABELS.get(value, value or "")


def _register_models():
    from app import models  # noqa: F401  (registers the 5 tables in SQLAlchemy metadata)


def _require_strong_secret(app):
    """Refuse to boot production on a guessable SECRET_KEY."""
    secret = app.config.get("SECRET_KEY") or ""
    if secret == "dev-secret-change-me" or not secret:
        raise RuntimeError(
            "SECRET_KEY must be set to a unique value in production; the app "
            "refuses to start on the development default.\n"
            'Generate one with: python -c "import secrets;print(secrets.token_hex(32))"'
        )
    if len(secret) < 32:
        raise RuntimeError(
            f"SECRET_KEY is only {len(secret)} characters; production requires "
            "at least 32."
        )


def _configure_proxy(app):
    """Rewrite request.remote_addr from X-Forwarded-* — but only when told to.

    The default TRUSTED_PROXY_HOPS is 0, so a request's own X-Forwarded-For
    header is ignored: an anonymous client cannot pick a fresh apparent IP per
    request and therefore cannot reset the login throttle. Deployments behind
    nginx/Caddy set TRUSTED_PROXY_HOPS=1 (2 behind a CDN/LB) and get the real
    client address back, which is also what logs and throttling key on.
    """
    hops = int(app.config.get("TRUSTED_PROXY_HOPS", 0) or 0)
    if hops <= 0:
        return
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(  # type: ignore[assignment]
        app.wsgi_app,
        x_for=hops,
        x_proto=hops,
        x_host=hops,
        x_port=hops,
        x_prefix=hops,
    )


def _ensure_instance_folder(app):
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///") and not uri.startswith("sqlite:///:memory:"):
        db_path = uri.replace("sqlite:///", "", 1)
        folder = os.path.dirname(db_path)
        if folder:
            os.makedirs(folder, exist_ok=True)


def _register_blueprints(app):
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.dashboard import bp as dashboard_bp
    from app.blueprints.drivers import bp as drivers_bp
    from app.blueprints.expenses import bp as expenses_bp
    from app.blueprints.fuel import bp as fuel_bp
    from app.blueprints.maintenance import bp as maintenance_bp
    from app.blueprints.more import bp as more_bp
    from app.blueprints.projects import bp as projects_bp
    from app.blueprints.reports import bp as reports_bp
    from app.blueprints.trips import bp as trips_bp
    from app.blueprints.users import bp as users_bp
    from app.blueprints.vehicles import bp as vehicles_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(dashboard_bp, url_prefix="/")
    app.register_blueprint(vehicles_bp, url_prefix="/vehicles")
    app.register_blueprint(trips_bp, url_prefix="/trips")
    app.register_blueprint(drivers_bp, url_prefix="/drivers")
    app.register_blueprint(fuel_bp, url_prefix="/fuel")
    app.register_blueprint(maintenance_bp, url_prefix="/maintenance")
    app.register_blueprint(expenses_bp, url_prefix="/expenses")
    app.register_blueprint(projects_bp, url_prefix="/projects")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(more_bp, url_prefix="/more")


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html"), 500


def _register_cli(app):
    from app.cli import register_commands

    register_commands(app)

    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        click_echo("Database initialized: all tables created.")


def _register_shell_context(app):
    @app.shell_context_processor
    def make_shell_context():
        ctx = {"db": db}
        try:
            from app.models import (
                Driver,
                Expense,
                FuelLog,
                MaintenanceLog,
                Project,
                TripLog,
                User,
                Vehicle,
                VehicleType,
            )

            ctx.update(
                Vehicle=Vehicle,
                VehicleType=VehicleType,
                TripLog=TripLog,
                FuelLog=FuelLog,
                MaintenanceLog=MaintenanceLog,
                Driver=Driver,
                Expense=Expense,
                Project=Project,
                User=User,
            )
        except ImportError:
            app.logger.info("Models not available yet (Task 2 pending); shell exposes db only.")
        return ctx


def click_echo(msg):
    import click

    click.echo(msg)
