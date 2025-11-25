import time
from datetime import datetime

from aiohttp import web

from logger import get_logger

logger = get_logger("api.routes")


async def health(request):
    return web.json_response({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})


async def status(request):
    return web.json_response({"status": "running", "uptime": time.process_time()})


def setup_routes(app):
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
