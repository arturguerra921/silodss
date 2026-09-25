"""SiloDSS WSGI entry point for production deployments (e.g., Gunicorn / Render)."""

from src.view.view import app

# Expose WSGI application callable for Gunicorn
server = app.server