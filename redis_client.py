import os

import redis.asyncio as redis

from logger import get_logger

logger = get_logger("redis")


class RedisClient:
    """Redis connection manager"""

    def __init__(self):
        self.client: redis.Redis | None = None
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    async def connect(self):
        """Connect to Redis"""
        if self.client is None:
            self.client = await redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            logger.info(f"Connected: {self.redis_url}")

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("Disconnected")

    def get_client(self) -> redis.Redis:
        """Get Redis client instance"""
        if self.client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self.client


# Global Redis client instance
redis_client = RedisClient()
