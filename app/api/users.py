# /app/api/users.py

from fastapi import APIRouter, HTTPException
from app.models.user import User
from pydantic import EmailStr

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/register")
async def register_user(email: EmailStr, full_name: str = ""):
    user = await User.find_one(User.email == email)
    if user:
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(email=email, full_name=full_name)
    await user.insert()
    return {"id": str(user.id), "email": user.email}
