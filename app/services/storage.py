import os
from typing import Union
from pathlib import Path

BASE_PATH = Path(os.getenv("STORAGE_PATH", "/backend/storage"))

def save_file(user_id: str, meeting_id: str, artifact_type: str, file_name: str, content: Union[bytes, str]) -> str:
    artifact_dir = BASE_PATH / user_id / meeting_id / artifact_type
    artifact_dir.mkdir(parents=True, exist_ok=True)
    file_path = artifact_dir / file_name

    if isinstance(content, str):
        content = content.encode("utf-8")
    with open(file_path, "wb") as f:
        f.write(content)
    return str(file_path)

def get_file_path(user_id: str, meeting_id: str, artifact_type: str, file_name: str) -> str:
    return str(BASE_PATH / user_id / meeting_id / artifact_type / file_name)
