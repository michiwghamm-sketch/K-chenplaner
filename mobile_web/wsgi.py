"""Entrypoint fuer WSGI-Server (z. B. gunicorn mobile_web.wsgi:app)."""

from mobile_web.server import create_app

app = create_app()
