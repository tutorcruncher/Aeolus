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

## Client Examples

### JavaScript

```javascript
import { io } from 'socket.io-client';

const socket = io('https://aeolus.herokuapp.com', {
  auth: { token: 'your-token' }
});

socket.on('connect', () => {
  socket.emit('channel:join', { channelId: 'chat-123' });
});

socket.on('message:received', (data) => {
  console.log('Message:', data);
});

socket.emit('message:send', {
  channelId: 'chat-123',
  data: { text: 'Hello!' }
});
```

### Python

```python
import socketio

sio = socketio.Client()

@sio.event
def connect():
    sio.emit('channel:join', {'channelId': 'chat-123'})

@sio.on('message:received')
def on_message(data):
    print(f'Message: {data}')

sio.connect('https://aeolus.herokuapp.com', auth={'token': 'your-token'})
sio.emit('message:send', {'channelId': 'chat-123', 'data': {'text': 'Hello!'}})
```

## Heroku Deployment

```bash
heroku create aeolus
heroku addons:create heroku-redis:mini
heroku config:set CORS_ORIGIN=https://your-domain.com
heroku config:set AUTH_TOKEN_PREFIX=tc2:socket:auth
git push heroku main
```

## License

MIT
