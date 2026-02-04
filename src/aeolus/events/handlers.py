import logging

import socketio
from cryptography.fernet import Fernet, InvalidToken

from src.aeolus.utils import utc_now_iso

logger = logging.getLogger("aeolus.socket")

TOKEN_TTL_SECONDS = 86400  # 24 hours


def validate_auth_token(token: str, fernet_key: str | None) -> dict | None:
    """Decrypt and validate a Fernet-encrypted authentication token.

    Token payload format (after decryption): "user_id:role_id:session_id"
    TTL: 24 hours.
    """
    if not fernet_key:
        logger.error("Fernet key not configured")
        return None

    f = Fernet(fernet_key)

    try:
        decrypted = f.decrypt(token.encode(), ttl=TOKEN_TTL_SECONDS).decode("utf-8")
    except InvalidToken:
        logger.warning("Invalid or expired token")
        return None

    parts = decrypted.split(":")
    if len(parts) != 3:
        logger.warning(f"Invalid token format: expected 3 parts, got {len(parts)}")
        return None

    user_id_str, role_id_str, session_id_str = parts

    try:
        user_id = int(user_id_str)
        role_id = int(role_id_str)
        session_id = int(session_id_str)
    except ValueError:
        logger.warning("Token contains non-integer IDs")
        return None

    logger.info(f"Token validated for user: {user_id}")
    return {
        "userId": user_id,
        "roleId": role_id,
        "chatSessionId": session_id,
    }


class SocketEventHandlers:
    def __init__(self, sio: socketio.AsyncServer, fernet_key: str | None):
        self.sio = sio
        self.fernet_key = fernet_key

    async def connect(self, sid: str, environ: dict, auth: dict | None) -> bool | None:
        token = auth.get("token") if auth else None

        if not token:
            logger.warning(f"No token provided: {sid}")
            return False

        session_data = validate_auth_token(token, self.fernet_key)

        if not session_data:
            logger.warning(f"Invalid token: {sid}")
            return False

        await self.sio.save_session(sid, session_data)
        logger.info(f"Connected: {sid} (user: {session_data['userId']})")
        return None

    async def disconnect(self, sid: str) -> None:
        try:
            session = await self.sio.get_session(sid)
        except KeyError:
            logger.info(f"Disconnected: {sid}")
            return
        logger.info(f"Disconnected: {sid} (user: {session.get('userId')})")

    async def channel_join(self, sid: str, data: dict) -> None:
        channel_id = data.get("channelId")

        if not channel_id:
            await self.sio.emit("error", {"message": "channelId required"}, to=sid)
            return

        session = await self.sio.get_session(sid)
        user_id = session.get("userId")
        authorized_session_id = session.get("chatSessionId")

        if str(authorized_session_id) != str(channel_id):
            logger.warning(
                f"User {user_id} ({sid}) unauthorized for channel {channel_id} (authorized for {authorized_session_id})"
            )
            await self.sio.emit("error", {"message": "Unauthorized for this channel"}, to=sid)
            return

        await self.sio.enter_room(sid, channel_id)
        logger.info(f"User {user_id} ({sid}) joined channel: {channel_id}")

        await self.sio.emit("channel:joined", {"channelId": channel_id}, to=sid)
        await self.sio.emit(
            "user:joined",
            {"userId": user_id, "channelId": channel_id},
            room=channel_id,
            skip_sid=sid,
        )

    async def channel_leave(self, sid: str, data: dict) -> None:
        channel_id = data.get("channelId")

        if not channel_id:
            return

        session = await self.sio.get_session(sid)
        user_id = session.get("userId")

        await self.sio.leave_room(sid, channel_id)
        logger.info(f"User {user_id} ({sid}) left channel: {channel_id}")
        await self.sio.emit("channel:left", {"channelId": channel_id}, to=sid)

        await self.sio.emit(
            "user:left",
            {"userId": user_id, "channelId": channel_id},
            room=channel_id,
        )

    async def message_send(self, sid: str, data: dict) -> None:
        channel_id = data.get("channelId")
        message_content = data.get("content")

        if not channel_id or not message_content:
            await self.sio.emit("error", {"message": "channelId and content required"}, to=sid)
            return

        session = await self.sio.get_session(sid)
        user_id = session.get("userId")

        logger.info(f"Message from user {user_id} in channel {channel_id}")
        await self.sio.emit(
            "message:received",
            {
                "channelId": channel_id,
                "senderId": user_id,
                "content": message_content,
                "timestamp": utc_now_iso(),
            },
            room=channel_id,
            skip_sid=sid,
        )

    async def message_read(self, sid: str, data: dict) -> None:
        channel_id = data.get("channelId")
        message_id = data.get("messageId")

        if not channel_id or not message_id:
            await self.sio.emit("error", {"message": "channelId and messageId required"}, to=sid)
            return

        session = await self.sio.get_session(sid)
        reader_id = session.get("userId")
        read_at = data.get("readAt") or utc_now_iso()
        complete = bool(data.get("complete"))
        readers = data.get("readers")

        payload = {
            "channelId": channel_id,
            "messageId": message_id,
            "readerId": reader_id,
            "readAt": read_at,
            "complete": complete,
        }
        if isinstance(readers, list):
            payload["readers"] = readers

        logger.info(
            f"Read receipt from user {reader_id} in channel {channel_id} (message {message_id}, complete={complete})"
        )
        await self.sio.emit("message:read", payload, room=channel_id, skip_sid=sid)


def setup_socket_events(sio: socketio.AsyncServer, fernet_key: str | None) -> None:
    handlers = SocketEventHandlers(sio, fernet_key)

    sio.on("connect", handlers.connect)
    sio.on("disconnect", handlers.disconnect)
    sio.on("channel_join", handlers.channel_join)
    sio.on("channel_leave", handlers.channel_leave)
    sio.on("message_send", handlers.message_send)
    sio.on("message_read", handlers.message_read)
