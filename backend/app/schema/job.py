from pydantic import BaseModel

class StartJobRequest(BaseModel):
    meeting_id: str
    job_type: str  # "recording", "transcription", "summarization"