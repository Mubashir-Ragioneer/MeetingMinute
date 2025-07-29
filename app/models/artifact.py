from beanie import Document, Link
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
from app.models.user import User

class Artifact(Document):
    user: Link[User]
    meeting_id: str = Field(...)
    artifact_type: Literal["audio", "transcript", "summary", "screenshot"]
    file_path: str = Field(...)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "artifacts"
