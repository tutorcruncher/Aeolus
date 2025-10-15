import json
import os
import time
from datetime import datetime

from aiohttp import web

from logger import get_logger

logger = get_logger("api.routes")
SERVER_SECRET = os.getenv("SERVER_SECRET")


async def health(request):
    return web.json_response({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})


async def status(request):
    return web.json_response({"status": "running", "uptime": time.process_time()})


async def init_channel(request):
    init_logger = get_logger("api.routes.init_channel")

    try:
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            init_logger.warning("Missing or invalid Authorization header")
            return web.json_response({"error": "Unauthorized"}, status=401)

        token = auth_header[7:]

        if token != SERVER_SECRET:
            init_logger.warning("Invalid secret token")
            return web.json_response({"error": "Unauthorized"}, status=401)

        data = await request.json()
        channel_id = data.get("channelId")

        if not channel_id:
            return web.json_response({"error": "channelId is required"}, status=400)

        metadata = data.get("metadata", {})

        init_logger.info(f"Channel initialized: {channel_id}", extra={"metadata": metadata})

        return web.json_response({"success": True, "channelId": channel_id})

    except json.JSONDecodeError:
        init_logger.error("Invalid JSON in request")
        return web.json_response({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        init_logger.error(f"Error: {e}")
        return web.json_response({"error": "Internal server error"}, status=500)


def setup_routes(app):
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_post("/init-channel", init_channel)
