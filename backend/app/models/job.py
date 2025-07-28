from beanie import Document, Link
from typing import Optional
from datetime import datetime
from app.models.user import User  # If you want to link the user

class Job(Document):
    job_id: str
    email: str
    meeting_url: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    params: Optional[dict] = None  
    save_dir: str  
    transcript: Optional[str] = None


    class Settings:
        name = "jobs"
