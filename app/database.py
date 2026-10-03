from motor.motor_asyncio import AsyncIOMotorClient 
from dotenv import load_dotenv
import os
import redis.asyncio as redis

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")
DB_NAME = os.getenv("DB_NAME")
REDIS_URL = os.getenv("REDIS_URL")

client = AsyncIOMotorClient(MONGODB_URL)
db = client[DB_NAME]
redis_client = redis.from_url(REDIS_URL)
