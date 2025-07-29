from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from app.models.artifact import Artifact
from app.models.user import User
from app.services.storage import save_file
from pydantic import EmailStr
from beanie.operators import In
from typing import List

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

@router.post("/upload")
async def upload_artifact(
    email: EmailStr = Form(...),
    meeting_id: str = Form(...),
    artifact_type: str = Form(...),
    file: UploadFile = File(...)
):
    # Look up user
    user = await User.find_one(User.email == email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    file_bytes = await file.read()
    file_path = save_file(str(user.id), meeting_id, artifact_type, file.filename, file_bytes)

    artifact = Artifact(
        user=user,
        meeting_id=meeting_id,
        artifact_type=artifact_type,
        file_path=file_path,
    )
    await artifact.insert()
    return {"ok": True, "file_path": file_path, "artifact_id": str(artifact.id)}


# List artifacts for a user or a meeting
@router.get("/", response_model=List[dict])
async def list_artifacts(
    email: EmailStr = Query(None),
    meeting_id: str = Query(None)
):
    query = {}
    if email:
        user = await User.find_one(User.email == email)
        if not user:
            return []
        query["user"] = user
    if meeting_id:
        query["meeting_id"] = meeting_id

    artifacts = await Artifact.find(query).to_list()
    return [
        {
            "id": str(a.id),
            "artifact_type": a.artifact_type,
            "file_path": a.file_path,
            "created_at": a.created_at,
        }
        for a in artifacts
    ]

# Optionally: Get single artifact (metadata)
@router.get("/{artifact_id}", response_model=dict)
async def get_artifact(artifact_id: str):
    artifact = await Artifact.get(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {
        "id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "file_path": artifact.file_path,
        "created_at": artifact.created_at,
    }
