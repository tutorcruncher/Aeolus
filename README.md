# Aeolus

**Aeolus** - God of the winds, delivering messages at lightning speed.

Generalized WebSocket server with Redis authentication for real-time communication.

## Features

- Redis-based authentication
- Channel management (rooms)
- Broadcasting with sender exclusion
- Typing indicators
- Python async/await with python-socketio

## Installation

```bash
uv sync
cp .env.example .env
```

## Configuration

```bash
PORT=3000
REDIS_URL=redis://localhost:6379
CORS_ORIGIN=*
AUTH_TOKEN_PREFIX=tc2:socket:auth
SERVER_SECRET=super-secret-token
SOCKETIO_REDIS_URL=redis://localhost:6379
```

### TC2 Integration

Store auth tokens in Redis:
```
Key:   {AUTH_TOKEN_PREFIX}:{token}
Value: JSON with userId, sessionId, etc.
```

## Development

```bash
uv run python server.py
```

## Production (Gunicorn)

```bash
gunicorn server:app --config gunicorn.conf.py
```

### Heroku

Use the included `Procfile`. For multi-worker deployments, set `SOCKETIO_REDIS_URL` (typically the same as
`REDIS_URL`) so Socket.IO events are broadcast across workers/dynos.

## HTTP API

### POST `/chat/read-receipt`

Used by TC2 to notify Aeolus that a chat message has been read by all participants. Requires the `SERVER_SECRET`
via `Authorization: Bearer <secret>`.

Payload:

```json
{
  "channelId": "chat_1",
  "messageId": 42,
  "readerId": 10,
  "readAt": "2026-01-06T12:00:00Z",
  "complete": true,
  "readers": [
    {"role_id": 10, "name": "Admin", "read_at": "2026-01-06T12:00:00Z"}
  ]
}
```

### POST `/chat/message`

Notifies Aeolus that TC2 has persisted a chat message. Requires the same `SERVER_SECRET`.

```json
{
  "channelId": "chat_1",
  "messageId": 42,
  "senderId": 10,
  "content": "Hello world",
  "timestamp": "2026-01-06T12:00:00Z",
  "senderName": "Admin"
}
```

## Socket Events

### Client → Server

- `channel:init` - Initialize channel
- `channel:join` - Join channel
- `channel:leave` - Leave channel
- `message:send` - Send message
- `broadcast` - Broadcast event
- `typing:start` / `typing:stop` - Typing indicators

### Server → Client

- `channel:initialized` - Channel created
- `channel:joined` - Joined confirmation
- `user:joined` - User joined channel
- `user:left` - User left channel
- `message:received` - Message received
- `typing:user` - User typing status
