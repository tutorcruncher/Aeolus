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
            auth_logger.warning(f"Token not found in Redis: {redis_key}")
            return None

        parsed_data = json.loads(session_data)
        user_id = parsed_data.get("userId") or parsed_data.get("user_id") or "unknown"
        auth_logger.info(f"Token validated for user: {user_id}")
        return parsed_data
    except Exception as e:
        auth_logger.error(f"Error validating token: {e}")
        return None


def setup_socket_events(sio: socketio.AsyncServer, auth_token_prefix: str):
    connect_logger = get_logger("socket.connect")
    disconnect_logger = get_logger("socket.disconnect")
    channel_logger = get_logger("socket.channel")

    @sio.event
    async def connect(sid, environ, auth):
        token = auth.get("token") if auth else None

        if not token:
            connect_logger.warning(f"No token provided for {sid}")
            return False

        session_data = await validate_auth_token(token, auth_token_prefix)

        if not session_data:
            connect_logger.warning(f"Invalid token for {sid}")
            return False

        await sio.save_session(
            sid,
            {
                "userId": session_data.get("userId") or session_data.get("user_id"),
                "sessionId": session_data.get("sessionId") or session_data.get("session_id"),
                "metadata": session_data,
            },
        )

        session = await sio.get_session(sid)
        connect_logger.info(f"Client connected: {sid} (user: {session.get('userId')})")

    @sio.event
    async def disconnect(sid):
        session = await sio.get_session(sid)
        disconnect_logger.info(f"Client disconnected: {sid} (user: {session.get('userId')})")

    @sio.event
    async def channel_init(sid, data):
        channel_id = data.get("channelId")
        metadata = data.get("metadata", {})
        channel_logger.info(f"Channel initialized: {channel_id}", extra={"metadata": metadata})
        await sio.emit("channel:initialized", {"channelId": channel_id, "success": True}, to=sid)

    @sio.event
    async def channel_join(sid, data):
        channel_id = data.get("channelId")
        session = await sio.get_session(sid)

        await sio.enter_room(sid, channel_id)
        channel_logger.info(f"Socket {sid} (user: {session.get('userId')}) joined channel: {channel_id}")

        await sio.emit("channel:joined", {"channelId": channel_id, "success": True}, to=sid)
        await sio.emit(
            "user:joined",
            {"userId": session.get("userId"), "socketId": sid, "channelId": channel_id},
            room=channel_id,
            skip_sid=sid,
        )

    @sio.event
    async def channel_leave(sid, data):
        channel_id = data.get("channelId")
        session = await sio.get_session(sid)

        await sio.leave_room(sid, channel_id)
        channel_logger.info(f"Socket {sid} (user: {session.get('userId')}) left channel: {channel_id}")

        await sio.emit("channel:left", {"channelId": channel_id, "success": True}, to=sid)
        await sio.emit(
            "user:left",
            {"userId": session.get("userId"), "socketId": sid, "channelId": channel_id},
            room=channel_id,
        )

    @sio.event
    async def message_send(sid, data):
        channel_id = data.get("channelId")
        message_data = data.get("data", {})
        metadata = data.get("metadata", {})
        session = await sio.get_session(sid)

        await sio.emit(
            "message:received",
            {
                **message_data,
                "senderId": session.get("userId"),
                "socketId": sid,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "metadata": metadata,
            },
            room=channel_id,
        )

    @sio.event
    async def broadcast(sid, data):
        channel_id = data.get("channelId")
        event = data.get("event")
        event_data = data.get("data", {})
        exclude_sender = data.get("excludeSender", True)

        if exclude_sender:
            await sio.emit(event, event_data, room=channel_id, skip_sid=sid)
        else:
            await sio.emit(event, event_data, room=channel_id)

    @sio.event
    async def typing_start(sid, data):
        channel_id = data.get("channelId")
        session = await sio.get_session(sid)

        await sio.emit("typing:user", {"userId": session.get("userId"), "typing": True}, room=channel_id, skip_sid=sid)

    @sio.event
    async def typing_stop(sid, data):
        channel_id = data.get("channelId")
        session = await sio.get_session(sid)

        await sio.emit("typing:user", {"userId": session.get("userId"), "typing": False}, room=channel_id, skip_sid=sid)
