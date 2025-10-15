import os
import redis.asyncio as redis
from typing import Optional
from logger import aeolus_logger


class RedisClient:
    """Redis connection manager"""

    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

    async def connect(self):
        """Connect to Redis"""
        if self.client is None:
            self.client = await redis.from_url(
                self.redis_url,
                encoding='utf-8',
                decode_responses=True
            )
            aeolus_logger.info(f'Connected to Redis: {self.redis_url}')

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.client:
            await self.client.close()
            self.client = None
            aeolus_logger.info('Disconnected from Redis')

    def get_client(self) -> redis.Redis:
        """Get Redis client instance"""
        if self.client is None:
            raise RuntimeError('Redis client not connected. Call connect() first.')
        return self.client


# Global Redis client instance
redis_client = RedisClient()
