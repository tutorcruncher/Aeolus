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
