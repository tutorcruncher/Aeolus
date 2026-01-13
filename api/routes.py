import json
import time
from datetime import datetime

from aiohttp import web

from logger import get_logger

logger = get_logger("api.routes")

_socket_server = None
_server_secret = None


async def health(request):
    return web.json_response({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})


async def status(request):
    return web.json_response({"status": "running", "uptime": time.process_time()})


def _auth_error_response(request: web.Request):
    if not _server_secret:
        logger.error("SERVER_SECRET is not configured; rejecting request")
        return web.json_response({"error": "Server secret missing"}, status=503)

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Unauthorized"}, status=401)

    token = auth_header.split(" ", 1)[1].strip()
    if token != _server_secret:
        return web.json_response({"error": "Unauthorized"}, status=401)
    return None


async def _parse_json(request: web.Request):
    try:
        return await request.json()
    except Exception:
        return None


async def read_receipt(request: web.Request):
    auth_error = _auth_error_response(request)
    if auth_error:
        return auth_error

    payload = await _parse_json(request)
    if payload is None:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    channel_id = payload.get("channelId")
    message_id = payload.get("messageId")

    if not channel_id or not message_id:
        return web.json_response({"error": "channelId and messageId are required"}, status=400)

    if _socket_server is None:
        logger.error("Socket server not configured; cannot emit read receipt")
        return web.json_response({"error": "Socket server unavailable"}, status=503)

    emit_payload = {
        "channelId": channel_id,
        "messageId": message_id,
        "complete": bool(payload.get("complete")),
    }

    if "readerId" in payload:
        emit_payload["readerId"] = payload["readerId"]
    if "readAt" in payload:
        emit_payload["readAt"] = payload["readAt"]
    if "readers" in payload and isinstance(payload["readers"], list):
        emit_payload["readers"] = payload["readers"]

    logger.info(
        "Broadcasting read receipt for channel %s message %s (complete=%s)",
        channel_id,
        message_id,
        emit_payload["complete"],
    )
    await _socket_server.emit("message:read", emit_payload, room=channel_id)
    return web.json_response({"success": True})


async def chat_message(request: web.Request):
    auth_error = _auth_error_response(request)
    if auth_error:
        return auth_error

    payload = await _parse_json(request)
    if payload is None:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    channel_id = payload.get("channelId")
    sender_id = payload.get("senderId")
    content = payload.get("content")
    message_id = payload.get("messageId")
    if not channel_id or not sender_id or not content or not message_id:
        return web.json_response(
            {"error": "channelId, senderId, content, and messageId are required"},
            status=400,
        )

    if _socket_server is None:
        logger.error("Socket server not configured; cannot emit message")
        return web.json_response({"error": "Socket server unavailable"}, status=503)

    emit_payload = {
        "channelId": channel_id,
        "senderId": sender_id,
        "content": content,
        "messageId": message_id,
        "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat() + "Z",
    }
    if "senderName" in payload:
        emit_payload["senderName"] = payload["senderName"]

    logger.info("Broadcasting chat message %s to channel %s", message_id, channel_id)
    await _socket_server.emit("message:received", emit_payload, room=channel_id)
    return web.json_response({"success": True})


def setup_routes(app, socket_server=None, server_secret=None):
    global _socket_server, _server_secret
    _socket_server = socket_server
    if server_secret is not None:
        _server_secret = server_secret

    app.router.add_get("/health", health)
    app.router.add_get("/status", status)
    app.router.add_post("/chat/read-receipt", read_receipt)
    app.router.add_post("/chat/message", chat_message)
