"""WSGI entry point for production servers.

    gunicorn --workers 3 --bind 0.0.0.0:8000 wsgi:app

Reads FLASK_CONFIG and SECRET_KEY from the environment. In production the app
refuses to start without a strong SECRET_KEY (see app/__init__.py).
"""
import os

from app import create_app

app = create_app(os.environ.get("FLASK_CONFIG", "production"))
