# pragma: no cover
"""Gunicorn configuration for Aeolus."""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"
worker_class = "aiohttp.worker.GunicornWebWorker"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))
wsgi_app = "src.aeolus.app:create_app()"
