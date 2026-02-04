import json
import logging
import time
from typing import TYPE_CHECKING

from aiohttp import web

from src.aeolus.utils import utc_now_iso

if TYPE_CHECKING:
    import socketio

logger = logging.getLogger("aeolus.api.handlers")


class APIHandlers:
    __slots__ = ("socket_server", "server_secret")

    def __init__(self, socket_server: "socketio.AsyncServer | None", server_secret: str | None):
        self.socket_server = socket_server
        self.server_secret = server_secret

    def _check_auth(self, request: web.Request) -> web.Response | None:
        if not self.server_secret:
            logger.error("SERVER_SECRET not configured")
            return web.json_response({"error": "Server secret missing"}, status=503)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Unauthorized"}, status=401)

        token = auth_header[7:].strip()
        if token != self.server_secret:
            return web.json_response({"error": "Unauthorized"}, status=401)
        return None

    def _check_socket_server(self) -> web.Response | None:
        if self.socket_server is None:
            logger.error("Socket server not configured")
            return web.json_response({"error": "Socket server unavailable"}, status=503)
        return None

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "timestamp": utc_now_iso()})

    async def status(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "running", "uptime": time.process_time()})

    async def read_receipt(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        channel_id = payload.get("channelId")
        message_id = payload.get("messageId")
        if not channel_id or not message_id:
            return web.json_response({"error": "channelId and messageId are required"}, status=400)

        if err := self._check_socket_server():
            return err

        emit_payload = {
            "channelId": channel_id,
            "messageId": message_id,
            "complete": bool(payload.get("complete")),
        }
        for key in ("readerId", "readAt"):
            if key in payload:
                emit_payload[key] = payload[key]
        if isinstance(payload.get("readers"), list):
            emit_payload["readers"] = payload["readers"]

        logger.info(
            "Broadcasting read receipt for channel %s message %s (complete=%s)",
            channel_id,
            message_id,
            emit_payload["complete"],
        )
        await self.socket_server.emit("message:read", emit_payload, room=channel_id)
        return web.json_response({"success": True})

    async def chat_message(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        required = ("channelId", "senderId", "content", "messageId")
        if not all(payload.get(k) for k in required):
            return web.json_response(
                {"error": "channelId, senderId, content, and messageId are required"},
                status=400,
            )

        if err := self._check_socket_server():
            return err

        emit_payload = {
            "channelId": payload["channelId"],
            "senderId": payload["senderId"],
            "content": payload["content"],
            "messageId": payload["messageId"],
            "timestamp": payload.get("timestamp") or utc_now_iso(),
        }
        if "senderName" in payload:
            emit_payload["senderName"] = payload["senderName"]

        logger.info("Broadcasting chat message %s to channel %s", payload["messageId"], payload["channelId"])
        await self.socket_server.emit("message:received", emit_payload, room=payload["channelId"])
        return web.json_response({"success": True})


def setup_routes(
    app: web.Application,
    socket_server: "socketio.AsyncServer | None",
    server_secret: str | None,
) -> None:
    handlers = APIHandlers(socket_server, server_secret)
    app.router.add_get("/health", handlers.health)
    app.router.add_get("/status", handlers.status)
    app.router.add_post("/chat/read-receipt", handlers.read_receipt)
    app.router.add_post("/chat/message", handlers.chat_message)
