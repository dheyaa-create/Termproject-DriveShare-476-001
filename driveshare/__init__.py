"""
DriveShare - Peer-to-Peer Car Rental Platform
=============================================

Application factory. ``create_app()`` builds a configured Flask app, wires the
database, the current-user hook (backed by the ``SessionManager`` Singleton)
and registers the route blueprints.

Run with ``python run.py`` (see README.md).
"""

import logging
import os
import secrets

from flask import Flask, g, url_for

from . import database
from .services import auth_service, car_service, notification_service


def create_app(test_config=None):
    """Create and configure a Flask application instance.

    Optional test settings override defaults before the database is initialized,
    allowing tests to use isolated databases and output files.
    """
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        # A random key per start-up keeps the cookie signature secret. Set
        # DRIVESHARE_SECRET in the environment for a stable key.
        SECRET_KEY=os.environ.get("DRIVESHARE_SECRET") or secrets.token_hex(32),
        DATABASE=os.path.join(app.instance_path, "driveshare.sqlite3"),
        EMAIL_OUTBOX=os.path.join(app.instance_path, "email_outbox.log"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    database.init_app(app)
    app.before_request(auth_service.load_current_user)

    @app.context_processor
    def inject_globals():
        """Make the unread-notification count available to every template."""
        user = g.get("user")
        count = notification_service.unread_count(database.get_db(), user["id"]) if user else 0
        return {"current_user": user, "unread_notifications": count}

    @app.template_filter("dt")
    def format_dt(value):
        """'2026-11-10T09:00' -> 'Nov 10, 2026 9:00 AM'."""
        from datetime import datetime
        try:
            return datetime.strptime(value[:16].replace(" ", "T"), "%Y-%m-%dT%H:%M") \
                .strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
        except (TypeError, ValueError):
            return value or ""

    @app.template_filter("car_image")
    def format_car_image(car):
        """Return a local image URL chosen for this listing's vehicle category."""
        filename = car_service.car_image_path(car["car_type"])
        return url_for("static", filename=filename)

    from .routes import api_bp, auth_bp, main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    return app
