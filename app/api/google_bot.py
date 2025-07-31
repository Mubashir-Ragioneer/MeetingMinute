# /app/api/google_bot.py

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path
from pydantic import BaseModel
import os
import subprocess
import uuid
import sys
import threading
from app.services.job_manager import job_manager
from app.models.job import Job
from datetime import datetime
import pytz
import asyncio
from app.services.transcribe import transcribe_audio
router = APIRouter(prefix="/bot", tags=["Googlebot"])

class BotJobRequest(BaseModel):
    email: str
    meeting_url: str
    duration: int = 120
    interval: int = 10
    save_dir: str = "storage"
    window_width: int = 1280
    window_height: int = 720
    leave_if_empty_secs: int = 30
    start_time: str = None
    headless: bool = True   


def set_job_status(job_id, update_fields):
    import asyncio
    from app.models.job import Job
    async def _do_update():
        job = await Job.find_one(Job.job_id == job_id)
        if job:
            await job.update({"$set": update_fields})
    asyncio.run(_do_update())

def monitor_process(job_id, proc):
    """Monitor process in a separate thread and update DB when done."""
    proc.wait()
    status = "finished" if proc.returncode == 0 else "error"
    import asyncio
    from app.models.job import Job
    from datetime import datetime
    async def update_status():
        await Job.find_one(Job.job_id == job_id).update({
            "$set": {"status": status, "finished_at": datetime.utcnow()}
        })
    asyncio.run(update_status())

def find_audio_file(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith('.wav'):
                return os.path.join(dirpath, filename)
    return None

def run_meeting_bot_threaded(
    email: str,
    meeting_url: str,
    duration: int,
    interval: int,
    save_dir: str,
    window_width: int,
    window_height: int,
    leave_if_empty_secs: int,
    start_time: str,
    job_id: str,
    headless: bool = True,
):

    bot_script = os.path.join(os.path.dirname(__file__), "../services/google_bot_runner.py")
    out_dir = os.path.abspath(os.path.join(save_dir, f"meeting_{job_id}"))
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        sys.executable, bot_script,
        "--email", email,
        "--meeting_url", meeting_url,
        "--duration", str(duration),
        "--interval", str(interval),
        "--save_dir", out_dir,
        "--window_width", str(window_width),
        "--window_height", str(window_height),
        "--leave_if_empty_secs", str(leave_if_empty_secs),
        "--headless", str(headless).lower(),   # <-- add this line
    ]

    if start_time:
        cmd += ["--start_time", start_time]

    proc = subprocess.Popen(cmd)
    job_manager.add(job_id, proc)
    proc.wait()

    status = "finished" if proc.returncode == 0 else "error"
    transcript = None

    # After recording, try to find audio file and transcribe it
        # After recording, try to find audio file (recursive) and transcribe it
    try:
        audio_path = find_audio_file(out_dir)
        if audio_path:
            transcript = transcribe_audio(audio_path)
        else:
            transcript = "No audio file found."
    except Exception as e:
        transcript = f"Transcription failed: {str(e)}"

    # Update job status and transcript in MongoDB
    def update_status_and_transcript_sync():
        import anyio
        async def _update():
            await Job.find_one(Job.job_id == job_id).update({
                "$set": {
                    "status": status,
                    "finished_at": datetime.utcnow(),
                    "transcript": transcript
                }
            })
        # this will schedule _update on the main FastAPI event loop
        anyio.from_thread.run(_update)
    update_status_and_transcript_sync()
    # You may log here, but not DB.

@router.post("/start", summary="Start a meeting bot job")
async def start_meeting_bot(req: BotJobRequest, background_tasks: BackgroundTasks):
    job_id = uuid.uuid4().hex
    out_dir = os.path.abspath(os.path.join(req.save_dir, f"meeting_{job_id}"))
    if req.start_time:
        start_dt = datetime.fromisoformat(req.start_time)
        if start_dt.tzinfo is None:
            start_dt = pytz.timezone("Asia/Karachi").localize(start_dt)
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
        if start_dt.astimezone(pytz.UTC) < now_utc:
            raise HTTPException(status_code=400, detail="Scheduled time is in the past")
    # Insert job record with status "pending"
    job = Job(
        job_id=job_id,
        email=req.email,
        meeting_url=req.meeting_url,
        status="pending",
        params=req.dict(),
        save_dir=out_dir,
    )
    await job.insert()

    # Set job status to "running" NOW (in main thread/loop)
    await Job.find_one(Job.job_id == job_id).update(
        {"$set": {"status": "running", "started_at": datetime.utcnow()}}
    )

    background_tasks.add_task(
        run_meeting_bot_threaded,
        req.email,
        req.meeting_url,
        req.duration,
        req.interval,
        out_dir,
        req.window_width,
        req.window_height,
        req.leave_if_empty_secs,
        req.start_time,
        job_id,
    )
    return {"message": "Bot started in background", "job_id": job_id}

@router.post("/cancel/{job_id}", summary="Cancel a scheduled meeting bot job")
async def cancel_meeting_bot(job_id: str = Path(..., description="Job ID returned by /bot/start")):
    result = job_manager.cancel(job_id)
    if result:
        await Job.find_one(Job.job_id == job_id).update({
            "$set": {"status": "cancelled", "finished_at": datetime.utcnow()}
        })
        return {"message": f"Job {job_id} cancelled"}
    raise HTTPException(status_code=404, detail="Job not found or already finished")

@router.get("/status/{job_id}", summary="Get status of a scheduled job")
async def job_status(job_id: str):
    job = await Job.find_one(Job.job_id == job_id)
    if not job:
        return {"job_id": job_id, "status": "not_found"}
    return {"job_id": job_id, "status": job.status}

@router.get("/list", summary="List all jobs")
async def list_jobs():
    jobs = await Job.find_all().to_list()
    return [
        {
            "job_id": j.job_id,
            "status": j.status,
            "email": j.email,
            "meeting_url": j.meeting_url,
            "save_dir": j.save_dir,
            "transcript": j.transcript
        }
        for j in jobs
    ]

@router.get("/info/{job_id}", summary="Get all details of a job by job_id")
async def get_job_info(job_id: str):
    job = await Job.find_one(Job.job_id == job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "email": job.email,
        "meeting_url": job.meeting_url,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration": job.params.get("duration") if job.params else None,
        "save_dir": job.save_dir,
        "transcript": getattr(job, "transcript", None)
    }
