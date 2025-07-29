from beanie import Document
from pydantic import EmailStr, Field
from typing import Optional

class User(Document):
    email: EmailStr = Field(...)
    full_name: Optional[str]
    # add more user fields as needed

    class Settings:
        name = "users"
