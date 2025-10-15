import os

import socketio
from aiohttp import web
from dotenv import load_dotenv

from api.routes import setup_routes
from events.socket import setup_socket_events
from logger import aeolus_logger
from redis_client import redis_client

load_dotenv()

PORT = int(os.getenv("PORT", "3000"))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
AUTH_TOKEN_PREFIX = os.getenv("AUTH_TOKEN_PREFIX", "tc2:socket:auth")

sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins=CORS_ORIGIN, logger=True, engineio_logger=False)

app = web.Application()
sio.attach(app)

setup_socket_events(sio, AUTH_TOKEN_PREFIX)
setup_routes(app)


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
