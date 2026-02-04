"""
Tests for multi-worker Socket.IO scenarios.

These tests verify that Aeolus behaves correctly when running with multiple workers
(e.g., via gunicorn with multiple processes). In multi-worker mode:

1. Each worker is a separate process with its own memory space
2. Socket.IO connections are distributed across workers
3. Without Redis manager, messages emitted in worker A won't reach clients in worker B
4. With Redis manager, messages are published to Redis and all workers subscribe

All tests use mocked Redis - no actual Redis connection required.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import socketio
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from src.aeolus.api import setup_routes
from src.aeolus.app import _build_socket_server, create_app, settings_key
from src.aeolus.events.handlers import SocketEventHandlers
from src.aeolus.settings import Settings
from tests.conftest import TEST_FERNET_KEY, create_test_token

TEST_SERVER_SECRET = "test-server-secret"
TEST_REDIS_URL = "redis://localhost:6379"


def create_mock_sio_with_sessions(worker_id: int | None = None, pubsub_channel=None):
    """
    Create a mock Socket.IO server with working session storage.

    This helper creates a properly configured mock that:
    - Stores sessions in a dict (like real Socket.IO)
    - Tracks all emitted events for assertions
    - Tracks room membership
    - Optionally integrates with a pub/sub channel for multi-worker tests
    """
    sio = MagicMock(spec=socketio.AsyncServer)
    sio.sessions = {}
    sio.rooms = {}  # Track room membership: {room_id: set(sids)}
    sio.emitted_events = []
    if worker_id is not None:
        sio.worker_id = worker_id

    async def save_session(sid, data):
        sio.sessions[sid] = data

    async def get_session(sid):
        return sio.sessions.get(sid, {})

    async def enter_room(sid, room):
        if room not in sio.rooms:
            sio.rooms[room] = set()
        sio.rooms[room].add(sid)

    async def leave_room(sid, room):
        if room in sio.rooms:
            sio.rooms[room].discard(sid)

    async def emit(event, data, room=None, to=None, skip_sid=None):
        source = "local" if pubsub_channel else None
        entry = {"event": event, "data": data, "room": room, "to": to, "skip_sid": skip_sid}
        if source:
            entry["source"] = source
        sio.emitted_events.append(entry)
        if pubsub_channel and room:
            await pubsub_channel.publish(event, data, room, skip_sid)

    sio.save_session = AsyncMock(side_effect=save_session)
    sio.get_session = AsyncMock(side_effect=get_session)
    sio.enter_room = AsyncMock(side_effect=enter_room)
    sio.leave_room = AsyncMock(side_effect=leave_room)
    sio.emit = AsyncMock(side_effect=emit)

    if pubsub_channel:

        async def on_pubsub_message(event, data, room, skip_sid):
            sio.emitted_events.append(
                {"event": event, "data": data, "room": room, "skip_sid": skip_sid, "source": "pubsub"}
            )

        pubsub_channel.subscribe(on_pubsub_message)

    return sio


@pytest.fixture
def mock_sio_with_sessions():
    """Module-level fixture for mock Socket.IO with session storage."""
    return create_mock_sio_with_sessions()


class TestRedisManagerWarning:
    """Tests for warning when SOCKETIO_REDIS_URL is not configured."""

    def test_warning_logged_when_redis_url_missing(self):
        """Verify warning is logged when SOCKETIO_REDIS_URL is not set.

        Without Redis manager, multi-worker mode will not work correctly because:
        - Each worker has isolated Socket.IO state
        - Messages emitted from worker A won't reach clients connected to worker B
        - Channel subscriptions are local to each worker
        """
        settings = Settings(
            port=3000,
            cors_origin="*",
            fernet_key=TEST_FERNET_KEY,
            server_secret=TEST_SERVER_SECRET,
            socketio_redis_url=None,
        )
        with patch("src.aeolus.app.logger") as mock_logger:
            _build_socket_server(settings, "*")
            mock_logger.warning.assert_called_once_with(
                "SOCKETIO_REDIS_URL not set - multi-worker mode will not work correctly"
            )

    def test_no_warning_when_redis_url_configured(self):
        """Verify no warning when SOCKETIO_REDIS_URL is properly configured."""
        settings = Settings(
            port=3000,
            cors_origin="*",
            fernet_key=TEST_FERNET_KEY,
            server_secret=TEST_SERVER_SECRET,
            socketio_redis_url=TEST_REDIS_URL,
        )
        with patch("src.aeolus.app.logger") as mock_logger:
            with patch("socketio.AsyncRedisManager"):
                _build_socket_server(settings, "*")
            mock_logger.warning.assert_not_called()

    def test_redis_manager_created_when_url_provided(self):
        """Verify AsyncRedisManager is instantiated with correct URL."""
        settings = Settings(
            port=3000,
            cors_origin="*",
            fernet_key=TEST_FERNET_KEY,
            server_secret=TEST_SERVER_SECRET,
            socketio_redis_url=TEST_REDIS_URL,
        )
        with patch("socketio.AsyncRedisManager") as mock_redis_manager:
            sio = _build_socket_server(settings, "*")
            mock_redis_manager.assert_called_once_with(TEST_REDIS_URL)
            assert sio is not None


class TestMultiWorkerMessageDelivery:
    """
    Tests for cross-worker message delivery via Redis pub/sub.

    In a multi-worker setup, when a message is emitted on one worker:
    1. The Redis manager publishes the message to a Redis channel
    2. All workers subscribe to that channel
    3. Each worker's Redis manager receives the message and emits locally

    These tests simulate this by creating separate handler instances
    (representing different workers) and verifying message propagation
    through a mock pub/sub channel.
    """

    @pytest.fixture
    def mock_pubsub_channel(self):
        """
        Simulates Redis pub/sub channel shared between workers.

        In production, this is handled by socketio.AsyncRedisManager which:
        - Publishes all emit() calls to Redis
        - Subscribes to Redis and re-emits messages locally

        The MockPubSub maintains a list of subscribers (worker callbacks)
        and broadcasts messages to all of them when publish is called.
        """
        subscribers = []

        class MockPubSub:
            def subscribe(self, callback):
                subscribers.append(callback)

            async def publish(self, event, data, room=None, skip_sid=None):
                for callback in subscribers:
                    await callback(event, data, room, skip_sid)

            def get_subscriber_count(self):
                return len(subscribers)

        return MockPubSub()

    @pytest.fixture
    def worker1_sio(self, mock_pubsub_channel):
        """Socket.IO server for worker 1 with pub/sub integration."""
        return create_mock_sio_with_sessions(worker_id=1, pubsub_channel=mock_pubsub_channel)

    @pytest.fixture
    def worker2_sio(self, mock_pubsub_channel):
        """Socket.IO server for worker 2 with pub/sub integration."""
        return create_mock_sio_with_sessions(worker_id=2, pubsub_channel=mock_pubsub_channel)

    @pytest.mark.asyncio
    async def test_complete_chat_flow_across_two_workers(self, worker1_sio, worker2_sio, mock_pubsub_channel):
        """
        Test a complete realistic chat flow between two users on different workers.

        This is the most important integration test - it simulates:
        1. Tutor (User 1) connects to Worker 1
        2. Student (User 2) connects to Worker 2
        3. Both join the same chat channel (session 100)
        4. Student sends a message -> Tutor receives it via pub/sub
        5. Tutor sends a reply -> Student receives it via pub/sub
        6. Tutor marks message as read -> Student sees read receipt
        7. Student disconnects -> Tutor is notified

        This tests the full lifecycle of a tutoring chat session.
        """
        handlers1 = SocketEventHandlers(worker1_sio, TEST_FERNET_KEY)
        handlers2 = SocketEventHandlers(worker2_sio, TEST_FERNET_KEY)

        # Verify pub/sub has 2 subscribers (one per worker)
        assert mock_pubsub_channel.get_subscriber_count() == 2

        # === STEP 1: Tutor connects to Worker 1 ===
        tutor_token = create_test_token(user_id=1, role_id=10, session_id=100)
        tutor_sid = "tutor-sid-worker1"

        connect_result = await handlers1.connect(tutor_sid, {}, {"token": tutor_token})
        assert connect_result is None, "Tutor connection should be accepted"

        # Verify session was saved on worker 1
        tutor_session = await worker1_sio.get_session(tutor_sid)
        assert tutor_session["userId"] == 1
        assert tutor_session["roleId"] == 10
        assert tutor_session["chatSessionId"] == 100

        # === STEP 2: Student connects to Worker 2 ===
        student_token = create_test_token(user_id=2, role_id=20, session_id=100)
        student_sid = "student-sid-worker2"

        connect_result = await handlers2.connect(student_sid, {}, {"token": student_token})
        assert connect_result is None, "Student connection should be accepted"

        # Verify session on worker 2 (isolated from worker 1)
        student_session = await worker2_sio.get_session(student_sid)
        assert student_session["userId"] == 2
        assert student_session["chatSessionId"] == 100

        # Verify worker 1 doesn't have student's session (isolation)
        cross_session = await worker1_sio.get_session(student_sid)
        assert cross_session == {}, "Worker 1 should not have Worker 2's sessions"

        # === STEP 3: Both users join channel 100 ===
        await handlers1.channel_join(tutor_sid, {"channelId": "100"})
        await handlers2.channel_join(student_sid, {"channelId": "100"})

        # Verify both are in their respective rooms
        assert tutor_sid in worker1_sio.rooms.get("100", set())
        assert student_sid in worker2_sio.rooms.get("100", set())

        # Clear events from setup phase
        worker1_sio.emitted_events.clear()
        worker2_sio.emitted_events.clear()

        # === STEP 4: Student sends message from Worker 2 ===
        await handlers2.message_send(
            student_sid,
            {
                "channelId": "100",
                "content": "Hi tutor, I need help with algebra!",
            },
        )

        # Verify message was emitted locally on worker 2
        worker2_local_msgs = [
            e for e in worker2_sio.emitted_events if e["event"] == "message:received" and e["source"] == "local"
        ]
        assert len(worker2_local_msgs) == 1
        assert worker2_local_msgs[0]["data"]["content"] == "Hi tutor, I need help with algebra!"
        assert worker2_local_msgs[0]["data"]["senderId"] == 2
        assert worker2_local_msgs[0]["room"] == "100"
        assert worker2_local_msgs[0]["skip_sid"] == student_sid  # Don't echo back to sender

        # Verify message propagated to worker 1 via pub/sub
        worker1_pubsub_msgs = [
            e for e in worker1_sio.emitted_events if e["event"] == "message:received" and e["source"] == "pubsub"
        ]
        assert len(worker1_pubsub_msgs) == 1
        assert worker1_pubsub_msgs[0]["data"]["content"] == "Hi tutor, I need help with algebra!"
        assert worker1_pubsub_msgs[0]["data"]["senderId"] == 2

        # === STEP 5: Tutor replies from Worker 1 ===
        worker1_sio.emitted_events.clear()
        worker2_sio.emitted_events.clear()

        await handlers1.message_send(
            tutor_sid,
            {
                "channelId": "100",
                "content": "Sure! What topic are you struggling with?",
            },
        )

        # Verify message propagated to worker 2 via pub/sub
        worker2_pubsub_msgs = [
            e for e in worker2_sio.emitted_events if e["event"] == "message:received" and e["source"] == "pubsub"
        ]
        assert len(worker2_pubsub_msgs) == 1
        assert worker2_pubsub_msgs[0]["data"]["content"] == "Sure! What topic are you struggling with?"
        assert worker2_pubsub_msgs[0]["data"]["senderId"] == 1

        # === STEP 6: Student marks message as read ===
        worker1_sio.emitted_events.clear()
        worker2_sio.emitted_events.clear()

        await handlers2.message_read(
            student_sid,
            {
                "channelId": "100",
                "messageId": "msg-001",
                "readAt": "2026-01-06T14:30:00Z",
                "complete": True,
                "readers": [{"role_id": 20, "name": "Student", "read_at": "2026-01-06T14:30:00Z"}],
            },
        )

        # Verify read receipt propagated to worker 1
        worker1_read_receipts = [
            e for e in worker1_sio.emitted_events if e["event"] == "message:read" and e["source"] == "pubsub"
        ]
        assert len(worker1_read_receipts) == 1
        assert worker1_read_receipts[0]["data"]["messageId"] == "msg-001"
        assert worker1_read_receipts[0]["data"]["readerId"] == 2
        assert worker1_read_receipts[0]["data"]["complete"] is True
        assert len(worker1_read_receipts[0]["data"]["readers"]) == 1

        # === STEP 7: Student leaves channel ===
        worker1_sio.emitted_events.clear()
        worker2_sio.emitted_events.clear()

        await handlers2.channel_leave(student_sid, {"channelId": "100"})

        # Verify user:left propagated to worker 1
        worker1_leave_events = [
            e for e in worker1_sio.emitted_events if e["event"] == "user:left" and e["source"] == "pubsub"
        ]
        assert len(worker1_leave_events) == 1
        assert worker1_leave_events[0]["data"]["userId"] == 2
        assert worker1_leave_events[0]["data"]["channelId"] == "100"

    @pytest.mark.asyncio
    async def test_multiple_messages_maintain_order_metadata(self, worker1_sio, worker2_sio):
        """
        Test that multiple rapid messages all include proper ordering metadata.

        In multi-worker setup, message order isn't guaranteed by Redis pub/sub.
        Each message must include:
        - timestamp: for client-side chronological ordering
        - senderId: to identify message author
        - channelId: to route to correct conversation

        This test sends 5 rapid messages and verifies all have proper metadata.
        """
        handlers1 = SocketEventHandlers(worker1_sio, TEST_FERNET_KEY)
        handlers2 = SocketEventHandlers(worker2_sio, TEST_FERNET_KEY)

        # Setup users
        token1 = create_test_token(user_id=1, role_id=10, session_id=100)
        token2 = create_test_token(user_id=2, role_id=20, session_id=100)

        await handlers1.connect("sid-1", {}, {"token": token1})
        await handlers2.connect("sid-2", {}, {"token": token2})
        await handlers1.channel_join("sid-1", {"channelId": "100"})
        await handlers2.channel_join("sid-2", {"channelId": "100"})

        worker1_sio.emitted_events.clear()
        worker2_sio.emitted_events.clear()

        # Send 5 messages rapidly from user 1
        messages = [
            "Message 1",
            "Message 2",
            "Message 3",
            "Message 4",
            "Message 5",
        ]
        for msg in messages:
            await handlers1.message_send("sid-1", {"channelId": "100", "content": msg})

        # Verify all messages reached worker 2 with proper metadata
        worker2_msgs = [
            e for e in worker2_sio.emitted_events if e["event"] == "message:received" and e["source"] == "pubsub"
        ]

        assert len(worker2_msgs) == 5, "All 5 messages should propagate"

        for i, event in enumerate(worker2_msgs):
            data = event["data"]
            assert data["content"] == messages[i]
            assert data["senderId"] == 1
            assert data["channelId"] == "100"
            assert "timestamp" in data, f"Message {i + 1} missing timestamp"
            assert data["timestamp"].endswith("Z"), f"Message {i + 1} timestamp not UTC ISO format"

    @pytest.mark.asyncio
    async def test_user_join_notification_includes_all_required_data(self, worker1_sio, worker2_sio):
        """
        Test that user:joined notifications contain all data needed for UI updates.

        When a user joins a channel, other participants need to know:
        - userId: to show who joined
        - channelId: to update the correct chat UI
        """
        handlers1 = SocketEventHandlers(worker1_sio, TEST_FERNET_KEY)

        token = create_test_token(user_id=42, role_id=10, session_id=100)
        await handlers1.connect("sid-42", {}, {"token": token})

        worker2_sio.emitted_events.clear()

        await handlers1.channel_join("sid-42", {"channelId": "100"})

        # Verify notification on worker 2
        join_events = [e for e in worker2_sio.emitted_events if e["event"] == "user:joined" and e["source"] == "pubsub"]

        assert len(join_events) == 1
        assert join_events[0]["data"]["userId"] == 42
        assert join_events[0]["data"]["channelId"] == "100"
        assert join_events[0]["room"] == "100"

    @pytest.mark.asyncio
    async def test_read_receipt_with_multiple_readers(self, worker1_sio, worker2_sio):
        """
        Test read receipt with multiple readers list (group chat scenario).

        In group chats, a message can be read by multiple people.
        The readers list tracks who has read the message.
        """
        handlers1 = SocketEventHandlers(worker1_sio, TEST_FERNET_KEY)

        token = create_test_token(user_id=1, role_id=10, session_id=100)
        await handlers1.connect("sid-1", {}, {"token": token})

        worker2_sio.emitted_events.clear()

        await handlers1.message_read(
            "sid-1",
            {
                "channelId": "100",
                "messageId": "msg-group-001",
                "readAt": "2026-01-06T15:00:00Z",
                "complete": False,  # Not everyone has read yet
                "readers": [
                    {"role_id": 10, "name": "Tutor A", "read_at": "2026-01-06T14:55:00Z"},
                    {"role_id": 20, "name": "Student B", "read_at": "2026-01-06T15:00:00Z"},
                ],
            },
        )

        read_events = [
            e for e in worker2_sio.emitted_events if e["event"] == "message:read" and e["source"] == "pubsub"
        ]

        assert len(read_events) == 1
        data = read_events[0]["data"]
        assert data["messageId"] == "msg-group-001"
        assert data["complete"] is False
        assert len(data["readers"]) == 2
        assert data["readers"][0]["name"] == "Tutor A"
        assert data["readers"][1]["name"] == "Student B"


class TestSessionIsolation:
    """
    Tests for session state isolation between workers.

    Socket.IO sessions are stored locally in each server instance.
    This means:
    - User session on worker 1 is NOT visible to worker 2
    - If user reconnects to different worker, they need to re-authenticate
    - Session data (userId, roleId, chatSessionId) is per-connection

    The current auth model uses stateless Fernet tokens, so users
    re-authenticate on each connection - this handles session isolation gracefully.
    """

    @pytest.fixture
    def isolated_worker1(self):
        """Worker 1 with isolated session storage."""
        return create_mock_sio_with_sessions()

    @pytest.fixture
    def isolated_worker2(self):
        """Worker 2 with isolated session storage."""
        return create_mock_sio_with_sessions()

    @pytest.mark.asyncio
    async def test_session_isolation_between_workers(self, isolated_worker1, isolated_worker2):
        """
        Verify that session data is completely isolated between workers.

        This is expected and correct behavior:
        - Each worker process has its own memory space
        - Socket.IO sessions are stored in-process
        - A session created on worker 1 cannot be read from worker 2
        """
        handlers1 = SocketEventHandlers(isolated_worker1, TEST_FERNET_KEY)

        # User connects to worker 1
        token = create_test_token(user_id=123, role_id=456, session_id=789)
        await handlers1.connect("sid-worker1", {}, {"token": token})

        # Session exists on worker 1 with full data
        session1 = await isolated_worker1.get_session("sid-worker1")
        assert session1["userId"] == 123
        assert session1["roleId"] == 456
        assert session1["chatSessionId"] == 789

        # Session does NOT exist on worker 2
        session2 = await isolated_worker2.get_session("sid-worker1")
        assert session2 == {}, "Session should not be visible on different worker"

        # Worker 2 has empty session store
        assert len(isolated_worker2.sessions) == 0
        assert len(isolated_worker1.sessions) == 1

    @pytest.mark.asyncio
    async def test_same_user_separate_sessions_per_worker(self, isolated_worker1, isolated_worker2):
        """
        Test that the same user connecting to both workers gets separate sessions.

        Scenario: User opens app in two browser tabs, load balancer routes to different workers.
        Each connection should have its own independent session.
        """
        handlers1 = SocketEventHandlers(isolated_worker1, TEST_FERNET_KEY)
        handlers2 = SocketEventHandlers(isolated_worker2, TEST_FERNET_KEY)

        # Same user, same token, different workers
        token = create_test_token(user_id=123, role_id=456, session_id=789)

        # Connect to worker 1
        await handlers1.connect("sid-tab1", {}, {"token": token})
        # Connect to worker 2
        await handlers2.connect("sid-tab2", {}, {"token": token})

        # Each worker has exactly one session
        assert len(isolated_worker1.sessions) == 1
        assert len(isolated_worker2.sessions) == 1

        # Sessions have same data but are independent
        session1 = await isolated_worker1.get_session("sid-tab1")
        session2 = await isolated_worker2.get_session("sid-tab2")

        assert session1["userId"] == session2["userId"] == 123
        assert session1 is not session2  # Different objects

    @pytest.mark.asyncio
    async def test_authentication_required_on_each_worker(self, isolated_worker1, isolated_worker2):
        """
        Verify that authentication is required independently on each worker.

        Even if user is authenticated on worker 1, they must re-authenticate
        when connecting to worker 2. This is the stateless auth model.
        """
        handlers1 = SocketEventHandlers(isolated_worker1, TEST_FERNET_KEY)
        handlers2 = SocketEventHandlers(isolated_worker2, TEST_FERNET_KEY)

        token = create_test_token(user_id=123, role_id=456, session_id=789)

        # Authenticate on worker 1
        result1 = await handlers1.connect("sid-w1", {}, {"token": token})
        assert result1 is None  # Accepted

        # Try to connect to worker 2 WITHOUT token - must fail
        result2_no_token = await handlers2.connect("sid-w2-fail", {}, None)
        assert result2_no_token is False  # Rejected

        # Connect to worker 2 WITH token - succeeds
        result2_with_token = await handlers2.connect("sid-w2-ok", {}, {"token": token})
        assert result2_with_token is None  # Accepted

    @pytest.mark.asyncio
    async def test_disconnect_only_affects_local_worker(self, isolated_worker1, isolated_worker2):
        """
        Test that disconnecting from one worker doesn't affect other workers.

        User connected to both workers, then disconnects from worker 1.
        Their session on worker 2 should remain intact.
        """
        handlers1 = SocketEventHandlers(isolated_worker1, TEST_FERNET_KEY)
        handlers2 = SocketEventHandlers(isolated_worker2, TEST_FERNET_KEY)

        token = create_test_token(user_id=123, role_id=456, session_id=789)

        # Connect to both workers
        await handlers1.connect("sid-w1", {}, {"token": token})
        await handlers2.connect("sid-w2", {}, {"token": token})

        # Both have sessions
        assert "sid-w1" in isolated_worker1.sessions
        assert "sid-w2" in isolated_worker2.sessions

        # Disconnect from worker 1 (just call disconnect handler)
        await handlers1.disconnect("sid-w1")

        # Worker 2 session is unaffected (disconnect doesn't clear session)
        # Note: In real Socket.IO, session cleanup happens on disconnect,
        # but our mock doesn't delete sessions on disconnect
        assert "sid-w2" in isolated_worker2.sessions


class TestSameUserMultipleConnections:
    """
    Tests for same user connected via multiple connections/workers.

    Common scenarios:
    - User has multiple browser tabs open
    - User on phone and laptop simultaneously
    - Load balancer routes connections to different workers
    """

    @pytest.mark.asyncio
    async def test_same_user_multiple_tabs_same_channel(self, mock_sio_with_sessions):
        """
        Test same user with multiple connections to the same channel.

        User 123 connects twice (two browser tabs), both joining channel 100.
        Both connections should be in the same room and receive messages.
        """
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        token = create_test_token(user_id=123, role_id=456, session_id=100)

        # Connection 1 (Tab 1)
        await handlers.connect("sid-tab1", {}, {"token": token})
        await handlers.channel_join("sid-tab1", {"channelId": "100"})

        # Connection 2 (Tab 2)
        await handlers.connect("sid-tab2", {}, {"token": token})
        await handlers.channel_join("sid-tab2", {"channelId": "100"})

        # Both should be in room 100
        assert "sid-tab1" in mock_sio_with_sessions.rooms["100"]
        assert "sid-tab2" in mock_sio_with_sessions.rooms["100"]

        # Both sessions exist independently
        assert mock_sio_with_sessions.sessions["sid-tab1"]["userId"] == 123
        assert mock_sio_with_sessions.sessions["sid-tab2"]["userId"] == 123

    @pytest.mark.asyncio
    async def test_same_user_different_authorized_channels(self, mock_sio_with_sessions):
        """
        Test same user with connections authorized for different channels.

        User 123 has two chat sessions:
        - Session 100: Chat with Tutor A
        - Session 200: Chat with Tutor B

        Each connection can only join its authorized channel.
        """
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        token_100 = create_test_token(user_id=123, role_id=456, session_id=100)
        token_200 = create_test_token(user_id=123, role_id=456, session_id=200)

        # Connection 1 - authorized for channel 100
        await handlers.connect("sid-100", {}, {"token": token_100})
        await handlers.channel_join("sid-100", {"channelId": "100"})

        # Connection 2 - authorized for channel 200
        await handlers.connect("sid-200", {}, {"token": token_200})
        await handlers.channel_join("sid-200", {"channelId": "200"})

        # Verify correct room membership
        assert "sid-100" in mock_sio_with_sessions.rooms["100"]
        assert "sid-200" in mock_sio_with_sessions.rooms["200"]
        assert "sid-100" not in mock_sio_with_sessions.rooms.get("200", set())
        assert "sid-200" not in mock_sio_with_sessions.rooms.get("100", set())

    @pytest.mark.asyncio
    async def test_cross_channel_join_attempt_rejected(self, mock_sio_with_sessions):
        """
        Test that connection cannot join channel it's not authorized for.

        Security test: Even if user is authenticated, they can only
        join the channel specified in their token's chatSessionId.
        """
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        # Token authorizes only channel 100
        token = create_test_token(user_id=123, role_id=456, session_id=100)
        await handlers.connect("sid-1", {}, {"token": token})

        # Try to join channel 200 - should be rejected
        mock_sio_with_sessions.emitted_events.clear()
        await handlers.channel_join("sid-1", {"channelId": "200"})

        # Should have emitted error, not joined room
        assert "sid-1" not in mock_sio_with_sessions.rooms.get("200", set())

        error_events = [e for e in mock_sio_with_sessions.emitted_events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["message"] == "Unauthorized for this channel"
        assert error_events[0]["to"] == "sid-1"


class TestHTTPAPIMultiWorkerPropagation(AioHTTPTestCase):
    """
    Tests for HTTP API event propagation in multi-worker setup.

    The Django backend uses HTTP API to send messages/receipts.
    These must propagate to all workers via Socket.IO rooms.
    """

    async def get_application(self):
        """Create test app with mocked Socket.IO server."""
        app = web.Application()
        self.mock_sio = AsyncMock()
        self.mock_sio.emit = AsyncMock()
        setup_routes(app, socket_server=self.mock_sio, server_secret=TEST_SERVER_SECRET)
        return app

    async def test_chat_message_full_payload(self):
        """
        Test POST /chat/message with complete payload including optional fields.

        The API accepts messages from Django and broadcasts to Socket.IO room.
        This tests all fields: channelId, senderId, content, messageId, timestamp, senderName.
        """
        headers = {"Authorization": f"Bearer {TEST_SERVER_SECRET}"}
        payload = {
            "channelId": "chat_100",
            "senderId": 7,
            "content": "Hello from Django backend!",
            "messageId": 55,
            "timestamp": "2026-01-06T12:00:00Z",
            "senderName": "John Doe",
        }

        r = await self.client.request("POST", "/chat/message", json=payload, headers=headers)
        assert r.status == 200

        data = await r.json()
        assert data["success"] is True

        # Verify emit call
        self.mock_sio.emit.assert_awaited_once()
        call_args = self.mock_sio.emit.call_args

        assert call_args[0][0] == "message:received"
        emit_data = call_args[0][1]
        assert emit_data["channelId"] == "chat_100"
        assert emit_data["senderId"] == 7
        assert emit_data["content"] == "Hello from Django backend!"
        assert emit_data["messageId"] == 55
        assert emit_data["timestamp"] == "2026-01-06T12:00:00Z"
        assert emit_data["senderName"] == "John Doe"
        assert call_args[1]["room"] == "chat_100"

    async def test_chat_message_generates_timestamp_if_missing(self):
        """
        Test that timestamp is auto-generated when not provided.
        """
        headers = {"Authorization": f"Bearer {TEST_SERVER_SECRET}"}
        payload = {
            "channelId": "chat_100",
            "senderId": 7,
            "content": "Message without timestamp",
            "messageId": 56,
            # No timestamp provided
        }

        r = await self.client.request("POST", "/chat/message", json=payload, headers=headers)
        assert r.status == 200

        call_args = self.mock_sio.emit.call_args
        emit_data = call_args[0][1]

        assert "timestamp" in emit_data
        assert emit_data["timestamp"].endswith("Z")  # UTC ISO format

    async def test_read_receipt_full_payload(self):
        """
        Test POST /chat/read-receipt with complete payload including readers list.
        """
        headers = {"Authorization": f"Bearer {TEST_SERVER_SECRET}"}
        payload = {
            "channelId": "chat_100",
            "messageId": 42,
            "readerId": 9,
            "readAt": "2026-01-06T12:30:00Z",
            "complete": True,
            "readers": [
                {"role_id": 9, "name": "Reader One", "read_at": "2026-01-06T12:30:00Z"},
                {"role_id": 10, "name": "Reader Two", "read_at": "2026-01-06T12:31:00Z"},
            ],
        }

        r = await self.client.request("POST", "/chat/read-receipt", json=payload, headers=headers)
        assert r.status == 200

        call_args = self.mock_sio.emit.call_args
        assert call_args[0][0] == "message:read"

        emit_data = call_args[0][1]
        assert emit_data["channelId"] == "chat_100"
        assert emit_data["messageId"] == 42
        assert emit_data["readerId"] == 9
        assert emit_data["readAt"] == "2026-01-06T12:30:00Z"
        assert emit_data["complete"] is True
        assert len(emit_data["readers"]) == 2
        assert call_args[1]["room"] == "chat_100"

    async def test_read_receipt_minimal_payload(self):
        """
        Test read receipt with only required fields (channelId, messageId).
        """
        headers = {"Authorization": f"Bearer {TEST_SERVER_SECRET}"}
        payload = {
            "channelId": "chat_100",
            "messageId": 43,
        }

        r = await self.client.request("POST", "/chat/read-receipt", json=payload, headers=headers)
        assert r.status == 200

        call_args = self.mock_sio.emit.call_args
        emit_data = call_args[0][1]

        assert emit_data["channelId"] == "chat_100"
        assert emit_data["messageId"] == 43
        assert emit_data["complete"] is False  # Default
        assert "readerId" not in emit_data
        assert "readAt" not in emit_data
        assert "readers" not in emit_data

    async def test_authentication_required(self):
        """Test that HTTP API requires valid Bearer token."""
        payload = {"channelId": "chat_100", "messageId": 1}

        # No auth header
        r = await self.client.request("POST", "/chat/read-receipt", json=payload)
        assert r.status == 401

        # Wrong token
        r = await self.client.request(
            "POST", "/chat/read-receipt", json=payload, headers={"Authorization": "Bearer wrong-secret"}
        )
        assert r.status == 401

        # Correct token
        r = await self.client.request(
            "POST", "/chat/read-receipt", json=payload, headers={"Authorization": f"Bearer {TEST_SERVER_SECRET}"}
        )
        assert r.status == 200


class TestChannelAuthorizationSecurity:
    """
    Security tests for channel authorization.

    The chatSessionId in the Fernet token determines which channel
    a user can join. This is the primary access control mechanism.
    """

    @pytest.mark.asyncio
    async def test_channel_id_string_int_comparison(self, mock_sio_with_sessions):
        """
        Test that channel authorization handles string/int comparison correctly.

        Token has int chatSessionId=100, client sends string channelId="100".
        The comparison uses str() on both sides, so this should work.
        """
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        # Token with int session_id
        token = create_test_token(user_id=1, role_id=10, session_id=100)
        await handlers.connect("sid-1", {}, {"token": token})

        # Client sends string channelId
        await handlers.channel_join("sid-1", {"channelId": "100"})

        # Should succeed
        assert "sid-1" in mock_sio_with_sessions.rooms["100"]

    @pytest.mark.asyncio
    async def test_cannot_join_without_channel_id(self, mock_sio_with_sessions):
        """Test that channelId is required to join a channel."""
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        token = create_test_token(user_id=1, role_id=10, session_id=100)
        await handlers.connect("sid-1", {}, {"token": token})

        mock_sio_with_sessions.emitted_events.clear()
        await handlers.channel_join("sid-1", {})  # No channelId

        error_events = [e for e in mock_sio_with_sessions.emitted_events if e["event"] == "error"]
        assert len(error_events) == 1
        assert "channelId required" in error_events[0]["data"]["message"]

    @pytest.mark.asyncio
    async def test_message_requires_channel_and_content(self, mock_sio_with_sessions):
        """Test that message_send requires both channelId and content."""
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        token = create_test_token(user_id=1, role_id=10, session_id=100)
        await handlers.connect("sid-1", {}, {"token": token})

        # Missing content
        mock_sio_with_sessions.emitted_events.clear()
        await handlers.message_send("sid-1", {"channelId": "100"})

        error_events = [e for e in mock_sio_with_sessions.emitted_events if e["event"] == "error"]
        assert len(error_events) == 1

        # Missing channelId
        mock_sio_with_sessions.emitted_events.clear()
        await handlers.message_send("sid-1", {"content": "Hello"})

        error_events = [e for e in mock_sio_with_sessions.emitted_events if e["event"] == "error"]
        assert len(error_events) == 1


class TestAppCreationMultiWorker:
    """
    Tests for app creation patterns in multi-worker context.

    Key requirement: Each worker must create its own fresh app instance.
    Using module-level singleton causes issues with forked processes.
    """

    def test_create_app_returns_fresh_instance_each_time(self):
        """Each call to create_app() returns a new Application instance."""
        settings = Settings(
            port=3000,
            cors_origin="*",
            fernet_key=TEST_FERNET_KEY,
            server_secret=TEST_SERVER_SECRET,
            socketio_redis_url=None,
        )

        with patch("src.aeolus.app.logger"):
            app1 = create_app(settings)
            app2 = create_app(settings)
            app3 = create_app(settings)

        # All should be different instances
        assert app1 is not app2
        assert app2 is not app3
        assert app1 is not app3

        # All should be valid Application instances
        assert isinstance(app1, web.Application)
        assert isinstance(app2, web.Application)
        assert isinstance(app3, web.Application)

    def test_app_stores_settings_correctly(self):
        """App stores settings accessible at runtime."""
        settings = Settings(
            port=3001,
            cors_origin="https://example.com",
            fernet_key=TEST_FERNET_KEY,
            server_secret=TEST_SERVER_SECRET,
            socketio_redis_url=TEST_REDIS_URL,
        )

        with patch("src.aeolus.app.logger"):
            with patch("socketio.AsyncRedisManager"):
                app = create_app(settings)

        assert app[settings_key] is settings
        assert app[settings_key].port == 3001
        assert app[settings_key].cors_origin == "https://example.com"
        assert app[settings_key].socketio_redis_url == TEST_REDIS_URL

    def test_gunicorn_config_uses_app_factory(self):
        """Verify gunicorn.conf.py uses app factory pattern, not module singleton."""
        project_root = Path(__file__).parent.parent
        gunicorn_config = project_root / "gunicorn.conf.py"

        content = gunicorn_config.read_text()

        # Must use factory pattern
        assert "create_app()" in content, "Gunicorn must use app factory pattern"

        # Must NOT reference module-level app singleton
        assert 'wsgi_app = "src.aeolus.app:app"' not in content, (
            "Should not reference module-level app - causes issues with forked workers"
        )


class TestMessageMetadataForOrdering:
    """
    Tests for message metadata required for client-side ordering.

    Redis pub/sub doesn't guarantee message order across workers.
    Messages must include metadata for clients to order correctly.
    """

    @pytest.mark.asyncio
    async def test_message_includes_all_ordering_metadata(self, mock_sio_with_sessions):
        """
        Verify messages include all fields needed for ordering and display.

        Required fields:
        - channelId: route to correct conversation
        - senderId: identify message author
        - content: the actual message
        - timestamp: for chronological ordering
        """
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        token = create_test_token(user_id=42, role_id=10, session_id=100)
        await handlers.connect("sid-1", {}, {"token": token})

        mock_sio_with_sessions.emitted_events.clear()
        await handlers.message_send("sid-1", {"channelId": "100", "content": "Test message"})

        msg_events = [e for e in mock_sio_with_sessions.emitted_events if e["event"] == "message:received"]
        assert len(msg_events) == 1

        data = msg_events[0]["data"]
        assert data["channelId"] == "100"
        assert data["senderId"] == 42
        assert data["content"] == "Test message"
        assert "timestamp" in data
        assert data["timestamp"].endswith("Z")

    @pytest.mark.asyncio
    async def test_read_receipt_includes_correlation_ids(self, mock_sio_with_sessions):
        """
        Verify read receipts include IDs for correlating with messages.

        Required fields:
        - channelId: which conversation
        - messageId: which message was read
        - readerId: who read it
        """
        handlers = SocketEventHandlers(mock_sio_with_sessions, TEST_FERNET_KEY)

        token = create_test_token(user_id=42, role_id=10, session_id=100)
        await handlers.connect("sid-1", {}, {"token": token})

        mock_sio_with_sessions.emitted_events.clear()
        await handlers.message_read(
            "sid-1",
            {
                "channelId": "100",
                "messageId": "msg-999",
                "readAt": "2026-01-06T16:00:00Z",
            },
        )

        read_events = [e for e in mock_sio_with_sessions.emitted_events if e["event"] == "message:read"]
        assert len(read_events) == 1

        data = read_events[0]["data"]
        assert data["channelId"] == "100"
        assert data["messageId"] == "msg-999"
        assert data["readerId"] == 42
        assert data["readAt"] == "2026-01-06T16:00:00Z"
