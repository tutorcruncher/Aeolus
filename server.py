import os

import socketio
from aiohttp import web
from aiohttp_cors import ResourceOptions
from aiohttp_cors import setup as cors_setup
from dotenv import load_dotenv

from api.routes import setup_routes
from events.socket import setup_socket_events
from logger import aeolus_logger
from redis_client import redis_client

load_dotenv()

PORT = int(os.getenv("PORT", "3000"))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
AUTH_TOKEN_PREFIX = os.getenv("AUTH_TOKEN_PREFIX", "tc2:socket:auth")

# TODO This needs to be refactored
if CORS_ORIGIN == "*":
    cors_allowed_origins = "*"
else:
    cors_allowed_origins = [CORS_ORIGIN]

sio = socketio.AsyncServer(
    async_mode="aiohttp", cors_allowed_origins=cors_allowed_origins, logger=True, engineio_logger=True
)

app = web.Application()

cors_config = {
    CORS_ORIGIN: ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")
}
if CORS_ORIGIN == "*":
    cors_config = {
        "*": ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")
    }

cors = cors_setup(app, defaults=cors_config)

sio.attach(app)

setup_socket_events(sio, AUTH_TOKEN_PREFIX)
setup_routes(app)

# TODO Make this a decorator
for route in list(app.router.routes()):
    try:
        cors.add(route)
    except ValueError:
        pass


async def on_startup(app):
    await redis_client.connect()
    aeolus_logger.info(f"Socket server running on port {PORT}")
    aeolus_logger.info(f"Redis connected: {redis_client.redis_url}")
    aeolus_logger.info(f"CORS origin: {CORS_ORIGIN}")
    aeolus_logger.info(f"Auth token prefix: {AUTH_TOKEN_PREFIX}")


async def on_shutdown(app):
    await redis_client.disconnect()


app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
