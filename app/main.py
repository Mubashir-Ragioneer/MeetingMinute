# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from app.core.db import init_db
from app.api.artifacts import router as artifacts_router
from app.api.users import router as users_router
from app.api.google_bot import router as bot_router
from app.api import teams_bot
from app.api.zoom_bot import router as zoom_router

app = FastAPI(title="MinuteMate API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # set your frontend URL for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    await init_db()

app.include_router(artifacts_router)
app.include_router(users_router)
app.include_router(bot_router)
app.include_router(teams_bot.router)
app.include_router(zoom_router)

# Serve storage as static files (for dev)
app.mount("/files", StaticFiles(directory="storage"), name="files")
