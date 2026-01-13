import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import socketio

from events.socket import setup_socket_events, validate_auth_token
from redis_client import redis_client


@pytest.fixture
def mock_redis():
    with patch.object(redis_client, "get_client") as mock:
        yield mock


class TestValidateAuthToken:
    @pytest.mark.asyncio
    async def test_validate_auth_token_success(self, mock_redis):
        # Setup mock
        mock_client = AsyncMock()
        session_data = {"userId": "user123", "sessionId": "session456"}
        mock_client.get.return_value = json.dumps(session_data)
        mock_redis.return_value = mock_client

        # Test
        result = await validate_auth_token("test-token", "tc2:socket:auth")

        # Verify
        mock_client.get.assert_called_once_with("tc2:socket:auth:test-token")
        assert result == session_data
        assert result["userId"] == "user123"
        assert result["sessionId"] == "session456"

    @pytest.mark.asyncio
    async def test_validate_auth_token_not_found(self, mock_redis):
        # Setup mock
        mock_client = AsyncMock()
        mock_client.get.return_value = None
        mock_redis.return_value = mock_client

        # Test
        result = await validate_auth_token("invalid-token", "tc2:socket:auth")

        # Verify
        mock_client.get.assert_called_once_with("tc2:socket:auth:invalid-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_auth_token_with_user_id_snake_case(self, mock_redis):
        # Setup mock with snake_case user_id
        mock_client = AsyncMock()
        session_data = {"user_id": "user789", "session_id": "session012"}
        mock_client.get.return_value = json.dumps(session_data)
        mock_redis.return_value = mock_client

        # Test
        result = await validate_auth_token("test-token", "tc2:socket:auth")

        # Verify
        assert result == session_data
        assert result["user_id"] == "user789"

    @pytest.mark.asyncio
    async def test_validate_auth_token_redis_error(self, mock_redis):
        # Setup mock to raise exception
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Redis connection error")
        mock_redis.return_value = mock_client

        # Test
        result = await validate_auth_token("test-token", "tc2:socket:auth")

        # Verify
        assert result is None


class TestSocketEvents:
    @pytest.fixture
    def sio(self):
        return socketio.AsyncServer(async_mode="aiohttp")

    @pytest.fixture
    def mock_sio(self):
        sio = MagicMock(spec=socketio.AsyncServer)
        sio.save_session = AsyncMock()
        sio.get_session = AsyncMock()
        sio.enter_room = AsyncMock()
        sio.leave_room = AsyncMock()
        sio.emit = AsyncMock()
        return sio

    @pytest.mark.asyncio
    async def test_connect_no_token(self, mock_sio, mock_redis):
        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the connect handler
        connect_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "connect":
                connect_handler = call[0][0]
                break

        if connect_handler:
            # Test with no auth
            result = await connect_handler("test-sid", {}, None)
            assert result is False

            # Test with empty auth
            result = await connect_handler("test-sid", {}, {})
            assert result is False

    @pytest.mark.asyncio
    async def test_connect_invalid_token(self, mock_sio, mock_redis):
        # Setup mock
        mock_client = AsyncMock()
        mock_client.get.return_value = None
        mock_redis.return_value = mock_client

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the connect handler
        connect_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "connect":
                connect_handler = call[0][0]
                break

        if connect_handler:
            result = await connect_handler("test-sid", {}, {"token": "invalid-token"})
            assert result is False

    @pytest.mark.asyncio
    async def test_connect_valid_token(self, mock_sio, mock_redis):
        # Setup mock
        mock_client = AsyncMock()
        session_data = {"userId": "user123", "sessionId": "session456"}
        mock_client.get.return_value = json.dumps(session_data)
        mock_redis.return_value = mock_client

        mock_sio.get_session.return_value = {"userId": "user123", "sessionId": "session456", "metadata": session_data}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the connect handler
        connect_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "connect":
                connect_handler = call[0][0]
                break

        if connect_handler:
            result = await connect_handler("test-sid", {}, {"token": "valid-token"})
            # Should not return False (authentication passed)
            assert result is None or result is not False
            mock_sio.save_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_channel_join(self, mock_sio):
        mock_sio.get_session.return_value = {"userId": "user123"}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the channel_join handler
        channel_join_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "channel_join":
                channel_join_handler = call[0][0]
                break

        if channel_join_handler:
            await channel_join_handler("test-sid", {"channelId": "channel123"})

            mock_sio.enter_room.assert_called_once_with("test-sid", "channel123")
            assert mock_sio.emit.call_count == 2  # channel:joined and user:joined

    @pytest.mark.asyncio
    async def test_channel_leave(self, mock_sio):
        mock_sio.get_session.return_value = {"userId": "user123"}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the channel_leave handler
        channel_leave_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "channel_leave":
                channel_leave_handler = call[0][0]
                break

        if channel_leave_handler:
            await channel_leave_handler("test-sid", {"channelId": "channel123"})

            mock_sio.leave_room.assert_called_once_with("test-sid", "channel123")
            assert mock_sio.emit.call_count == 2  # channel:left and user:left

    @pytest.mark.asyncio
    async def test_message_send(self, mock_sio):
        mock_sio.get_session.return_value = {"userId": "user123"}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the message_send handler
        message_send_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "message_send":
                message_send_handler = call[0][0]
                break

        if message_send_handler:
            await message_send_handler(
                "test-sid",
                {
                    "channelId": "channel123",
                    "content": "Hello",
                },
            )

            mock_sio.emit.assert_called_once()
            call_args = mock_sio.emit.call_args
            assert call_args[0][0] == "message:received"
            assert call_args[0][1]["senderId"] == "user123"
            assert call_args[0][1]["channelId"] == "channel123"
            assert call_args[0][1]["content"] == "Hello"
            assert "timestamp" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_broadcast_exclude_sender(self, mock_sio):
        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the broadcast handler
        broadcast_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "broadcast":
                broadcast_handler = call[0][0]
                break

        if broadcast_handler:
            await broadcast_handler(
                "test-sid",
                {"channelId": "channel123", "event": "custom:event", "data": {"key": "value"}, "excludeSender": True},
            )

            mock_sio.emit.assert_called_once_with(
                "custom:event", {"key": "value"}, room="channel123", skip_sid="test-sid"
            )

    @pytest.mark.asyncio
    async def test_broadcast_include_sender(self, mock_sio):
        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the broadcast handler
        broadcast_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "broadcast":
                broadcast_handler = call[0][0]
                break

        if broadcast_handler:
            await broadcast_handler(
                "test-sid",
                {"channelId": "channel123", "event": "custom:event", "data": {"key": "value"}, "excludeSender": False},
            )

            mock_sio.emit.assert_called_once_with("custom:event", {"key": "value"}, room="channel123")

    @pytest.mark.asyncio
    async def test_typing_start(self, mock_sio):
        mock_sio.get_session.return_value = {"userId": "user123"}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the typing_start handler
        typing_start_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "typing_start":
                typing_start_handler = call[0][0]
                break

        if typing_start_handler:
            await typing_start_handler("test-sid", {"channelId": "channel123"})

            mock_sio.emit.assert_called_once_with(
                "typing:user",
                {"userId": "user123", "channelId": "channel123", "typing": True},
                room="channel123",
                skip_sid="test-sid",
            )

    @pytest.mark.asyncio
    async def test_typing_stop(self, mock_sio):
        mock_sio.get_session.return_value = {"userId": "user123"}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        # Get the typing_stop handler
        typing_stop_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "typing_stop":
                typing_stop_handler = call[0][0]
                break

        if typing_stop_handler:
            await typing_stop_handler("test-sid", {"channelId": "channel123"})

            mock_sio.emit.assert_called_once_with(
                "typing:user",
                {"userId": "user123", "channelId": "channel123", "typing": False},
                room="channel123",
                skip_sid="test-sid",
            )

    @pytest.mark.asyncio
    async def test_message_read(self, mock_sio):
        mock_sio.get_session.return_value = {"userId": "user123"}

        setup_socket_events(mock_sio, "tc2:socket:auth")

        message_read_handler = None
        for call in mock_sio.event.call_args_list:
            if len(call[0]) > 0 and call[0][0].__name__ == "message_read":
                message_read_handler = call[0][0]
                break

        if message_read_handler:
            await message_read_handler(
                "test-sid",
                {
                    "channelId": "channel123",
                    "messageId": "msg-1",
                    "readAt": "2026-01-06T12:00:00Z",
                    "complete": True,
                    "readers": [{"role_id": 5, "name": "Tester", "read_at": "2026-01-06T12:00:00Z"}],
                },
            )

            mock_sio.emit.assert_called_with(
                "message:read",
                {
                    "channelId": "channel123",
                    "messageId": "msg-1",
                    "readerId": "user123",
                    "readAt": "2026-01-06T12:00:00Z",
                    "complete": True,
                    "readers": [{"role_id": 5, "name": "Tester", "read_at": "2026-01-06T12:00:00Z"}],
                },
                room="channel123",
                skip_sid="test-sid",
            )
