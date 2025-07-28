# app/core/db.py

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.user import User
from app.models.artifact import Artifact
from app.core.config import settings
from app.models.job import Job

client: AsyncIOMotorClient | None = None

async def init_db():
    global client
    uri = settings.MONGODB_URI
    db_name = settings.MONGODB_DB  # add this to your settings
    client = AsyncIOMotorClient(uri)
    await init_beanie(database=client[db_name], document_models=[User, Artifact, Job])
