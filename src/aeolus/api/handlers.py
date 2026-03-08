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

    async def user_read(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        channel_id = payload.get("channelId")
        reader_id = payload.get("readerId")
        reader_name = payload.get("readerName")
        if not channel_id or not reader_id:
            return web.json_response({"error": "channelId and readerId are required"}, status=400)

        if err := self._check_socket_server():
            return err

        emit_payload = {
            "channelId": channel_id,
            "readerId": reader_id,
            "readerName": reader_name or "",
        }

        logger.info("Broadcasting user read for channel %s reader %s", channel_id, reader_id)
        await self.socket_server.emit("chat:user_read", emit_payload, room=channel_id)
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
        if "replyToId" in payload:
            emit_payload["replyToId"] = payload["replyToId"]
        if "sequenceNumber" in payload:
            emit_payload["sequenceNumber"] = payload["sequenceNumber"]

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
    app.router.add_post("/chat/user-read", handlers.user_read)
    app.router.add_post("/chat/message", handlers.chat_message)
