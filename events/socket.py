import json
from datetime import datetime

import socketio

from logger import get_logger
from redis_client import redis_client

auth_logger = get_logger("socket.auth")


async def validate_auth_token(token: str, auth_token_prefix: str) -> dict:
    try:
        redis_key = f"{auth_token_prefix}:{token}"
        session_data = await redis_client.get_client().get(redis_key)

        if not session_data:
            auth_logger.warning(f"Token not found: {redis_key}")
            return None

        parsed_data = json.loads(session_data)
        user_id = parsed_data.get("userId") or parsed_data.get("user_id")
        auth_logger.info(f"Token validated for user: {user_id}")
        return parsed_data
    except Exception as e:
        auth_logger.error(f"Token validation error: {e}")
        return None


def setup_socket_events(sio: socketio.AsyncServer, auth_token_prefix: str):
    connect_logger = get_logger("socket.connect")
    disconnect_logger = get_logger("socket.disconnect")
    channel_logger = get_logger("socket.channel")
    message_logger = get_logger("socket.message")

    @sio.event
    async def connect(sid, environ, auth):
        token = auth.get("token") if auth else None

        if not token:
            connect_logger.warning(f"No token provided: {sid}")
            return False

        session_data = await validate_auth_token(token, auth_token_prefix)

        if not session_data:
            connect_logger.warning(f"Invalid token: {sid}")
            return False

        await sio.save_session(
            sid,
            {
                "userId": session_data.get("userId") or session_data.get("user_id"),
                "chatSessionId": session_data.get("chatSessionId") or session_data.get("chat_session_id"),
            },
        )

        session = await sio.get_session(sid)
        connect_logger.info(f"Connected: {sid} (user: {session.get('userId')})")

    @sio.event
    async def disconnect(sid):
        try:
            session = await sio.get_session(sid)
            disconnect_logger.info(f"Disconnected: {sid} (user: {session.get('userId')})")
        except Exception:
            disconnect_logger.info(f"Disconnected: {sid}")

    @sio.event
    async def channel_join(sid, data):
        channel_id = data.get("channelId")

        if not channel_id:
            await sio.emit("error", {"message": "channelId required"}, to=sid)
            return

        session = await sio.get_session(sid)
        user_id = session.get("userId")

        await sio.enter_room(sid, channel_id)
        channel_logger.info(f"User {user_id} ({sid}) joined channel: {channel_id}")

        await sio.emit("channel:joined", {"channelId": channel_id}, to=sid)
        await sio.emit(
            "user:joined",
            {"userId": user_id, "channelId": channel_id},
            room=channel_id,
            skip_sid=sid,
        )

    @sio.event
    async def channel_leave(sid, data):
        channel_id = data.get("channelId")

        if not channel_id:
            return

        session = await sio.get_session(sid)
        user_id = session.get("userId")

        await sio.leave_room(sid, channel_id)
        channel_logger.info(f"User {user_id} ({sid}) left channel: {channel_id}")
        await sio.emit("channel:left", {"channelId": channel_id}, to=sid)

        await sio.emit(
            "user:left",
            {"userId": user_id, "channelId": channel_id},
            room=channel_id,
        )

    @sio.event
    async def message_send(sid, data):
        channel_id = data.get("channelId")
        message_content = data.get("content")

        if not channel_id or not message_content:
            await sio.emit("error", {"message": "channelId and content required"}, to=sid)
            return

        session = await sio.get_session(sid)
        user_id = session.get("userId")

        message_logger.info(f"Message from user {user_id} in channel {channel_id}")
        await sio.emit(
            "message:received",
            {
                "channelId": channel_id,
                "senderId": user_id,
                "content": message_content,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
            room=channel_id,
            skip_sid=sid,
        )

    @sio.event
    async def typing_start(sid, data):
        channel_id = data.get("channelId")

        if not channel_id:
            return

        session = await sio.get_session(sid)
        user_id = session.get("userId")
        await sio.emit(
            "typing:user",
            {"userId": user_id, "channelId": channel_id, "typing": True},
            room=channel_id,
            skip_sid=sid,
        )

    @sio.event
    async def typing_stop(sid, data):
        channel_id = data.get("channelId")

        if not channel_id:
            return

        session = await sio.get_session(sid)
        user_id = session.get("userId")

        # Notify others (exclude sender)
        await sio.emit(
            "typing:user",
            {"userId": user_id, "channelId": channel_id, "typing": False},
            room=channel_id,
            skip_sid=sid,
        )
