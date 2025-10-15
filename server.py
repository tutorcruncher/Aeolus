import os
import json
import socketio
from aiohttp import web
from dotenv import load_dotenv
from redis_client import redis_client
from logger import aeolus_logger

load_dotenv()

PORT = int(os.getenv('PORT', '3000'))
CORS_ORIGIN = os.getenv('CORS_ORIGIN', '*')
AUTH_TOKEN_PREFIX = os.getenv('AUTH_TOKEN_PREFIX', 'tc2:socket:auth')
SERVER_SECRET = os.getenv('SERVER_SECRET')

sio = socketio.AsyncServer(
    async_mode='aiohttp',
    cors_allowed_origins=CORS_ORIGIN,
    logger=True,
    engineio_logger=False
)

app = web.Application()
sio.attach(app)


async def validate_auth_token(token: str) -> dict:
    try:
        redis_key = f'{AUTH_TOKEN_PREFIX}:{token}'
        session_data = await redis_client.get_client().get(redis_key)

        if not session_data:
            aeolus_logger.warning(f'Auth failed: Token not found in Redis: {redis_key}')
            return None

        parsed_data = json.loads(session_data)
        user_id = parsed_data.get('userId') or parsed_data.get('user_id') or 'unknown'
        aeolus_logger.info(f'Auth success: Token validated for user: {user_id}')
        return parsed_data
    except Exception as e:
        aeolus_logger.error(f'Error validating auth token: {e}')
        return None


@sio.event
async def connect(sid, environ, auth):
    token = auth.get('token') if auth else None

    if not token:
        aeolus_logger.warning(f'Auth failed: No token provided for {sid}')
        return False

    session_data = await validate_auth_token(token)

    if not session_data:
        aeolus_logger.warning(f'Auth failed: Invalid token for {sid}')
        return False

    await sio.save_session(sid, {
        'userId': session_data.get('userId') or session_data.get('user_id'),
        'sessionId': session_data.get('sessionId') or session_data.get('session_id'),
        'metadata': session_data
    })

    session = await sio.get_session(sid)
    aeolus_logger.info(f'Client connected: {sid} (user: {session.get("userId")})')


@sio.event
async def disconnect(sid):
    session = await sio.get_session(sid)
    aeolus_logger.info(f'Client disconnected: {sid} (user: {session.get("userId")})')


@sio.event
async def channel_init(sid, data):
    channel_id = data.get('channelId')
    metadata = data.get('metadata', {})
    aeolus_logger.info(f'Channel initialized: {channel_id}', extra={'metadata': metadata})
    await sio.emit('channel:initialized', {'channelId': channel_id, 'success': True}, to=sid)


@sio.event
async def channel_join(sid, data):
    channel_id = data.get('channelId')
    session = await sio.get_session(sid)

    await sio.enter_room(sid, channel_id)
    aeolus_logger.info(f'Socket {sid} (user: {session.get("userId")}) joined channel: {channel_id}')

    await sio.emit('channel:joined', {'channelId': channel_id, 'success': True}, to=sid)
    await sio.emit('user:joined', {
        'userId': session.get('userId'),
        'socketId': sid,
        'channelId': channel_id
    }, room=channel_id, skip_sid=sid)


@sio.event
async def channel_leave(sid, data):
    channel_id = data.get('channelId')
    session = await sio.get_session(sid)

    await sio.leave_room(sid, channel_id)
    aeolus_logger.info(f'Socket {sid} (user: {session.get("userId")}) left channel: {channel_id}')

    await sio.emit('channel:left', {'channelId': channel_id, 'success': True}, to=sid)
    await sio.emit('user:left', {
        'userId': session.get('userId'),
        'socketId': sid,
        'channelId': channel_id
    }, room=channel_id)


@sio.event
async def message_send(sid, data):
    channel_id = data.get('channelId')
    message_data = data.get('data', {})
    metadata = data.get('metadata', {})
    session = await sio.get_session(sid)

    from datetime import datetime

    await sio.emit('message:received', {
        **message_data,
        'senderId': session.get('userId'),
        'socketId': sid,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'metadata': metadata
    }, room=channel_id)


@sio.event
async def broadcast(sid, data):
    channel_id = data.get('channelId')
    event = data.get('event')
    event_data = data.get('data', {})
    exclude_sender = data.get('excludeSender', True)

    if exclude_sender:
        await sio.emit(event, event_data, room=channel_id, skip_sid=sid)
    else:
        await sio.emit(event, event_data, room=channel_id)


@sio.event
async def typing_start(sid, data):
    channel_id = data.get('channelId')
    session = await sio.get_session(sid)

    await sio.emit('typing:user', {
        'userId': session.get('userId'),
        'typing': True
    }, room=channel_id, skip_sid=sid)


@sio.event
async def typing_stop(sid, data):
    channel_id = data.get('channelId')
    session = await sio.get_session(sid)

    await sio.emit('typing:user', {
        'userId': session.get('userId'),
        'typing': False
    }, room=channel_id, skip_sid=sid)


async def health(request):
    from datetime import datetime
    return web.json_response({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })


async def status(request):
    import time
    return web.json_response({
        'status': 'running',
        'uptime': time.process_time()
    })


async def init_channel(request):
    try:
        auth_header = request.headers.get('Authorization')

        if not auth_header or not auth_header.startswith('Bearer '):
            aeolus_logger.warning('Channel init failed: Missing or invalid Authorization header')
            return web.json_response({'error': 'Unauthorized'}, status=401)

        token = auth_header[7:]

        if token != SERVER_SECRET:
            aeolus_logger.warning('Channel init failed: Invalid secret token')
            return web.json_response({'error': 'Unauthorized'}, status=401)

        data = await request.json()
        channel_id = data.get('channelId')

        if not channel_id:
            return web.json_response({'error': 'channelId is required'}, status=400)

        metadata = data.get('metadata', {})

        aeolus_logger.info(f'Channel initialized via HTTP: {channel_id}', extra={'metadata': metadata})

        return web.json_response({
            'success': True,
            'channelId': channel_id
        })

    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        aeolus_logger.error(f'Error initializing channel: {e}')
        return web.json_response({'error': 'Internal server error'}, status=500)


app.router.add_get('/health', health)
app.router.add_get('/status', status)
app.router.add_post('/init-channel', init_channel)


async def on_startup(app):
    await redis_client.connect()
    aeolus_logger.info(f'Socket server running on port {PORT}')
    aeolus_logger.info(f'Redis connected: {redis_client.redis_url}')
    aeolus_logger.info(f'CORS origin: {CORS_ORIGIN}')
    aeolus_logger.info(f'Auth token prefix: {AUTH_TOKEN_PREFIX}')


async def on_shutdown(app):
    await redis_client.disconnect()


app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)


if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=PORT)
