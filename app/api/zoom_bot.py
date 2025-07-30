# app/api/zoom_bot.py
from fastapi import APIRouter, BackgroundTasks, HTTPException, Path
from pydantic import BaseModel
import os, subprocess, uuid, sys
from datetime import datetime
import pytz

from app.services.job_manager import job_manager
from app.models.job import Job
from app.services.transcribe import transcribe_audio

router = APIRouter(prefix="/zoombot", tags=["ZoomBot"])

# ─────────────────────────────────────────────── Request schema
class ZoomBotJobRequest(BaseModel):
    email: str
    meeting_id: str
    passcode: str
    name: str = "MinuteMate Bot"
    duration: int = 120
    interval: int = 10
    save_dir: str = "storage"
    window_width: int = 1280
    window_height: int = 720
    leave_if_empty_secs: int = 30  
    start_time: str = None
    headless: bool = True

# ─────────────────────────────────────────────── helpers
def _find_audio(root_dir: str) -> str | None:
    for d, _, files in os.walk(root_dir):
        for f in files:
            if f.endswith(".wav"):
                return os.path.join(d, f)
    return None

def _run_zoom_bot_threaded(
    *,
    email: str,
    meeting_id: str,
    passcode: str,
    name: str,
    duration: int,
    interval: int,
    save_dir: str,
    window_width: int,
    window_height: int,
    leave_if_empty_secs: int,
    start_time: str | None,
    job_id: str,
    headless: bool,
):
    bot_script = os.path.join(os.path.dirname(__file__), "../services/zoom_bot_runner.py")
    out_dir = os.path.abspath(os.path.join(save_dir, f"meeting_{job_id}"))
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        sys.executable, bot_script,
        "--meeting_id", meeting_id,
        "--passcode", passcode,
        "--name", name,
        "--duration", str(duration),
        "--interval", str(interval),
        "--save_dir", out_dir,
        "--window_width", str(window_width),
        "--window_height", str(window_height),
        "--leave_if_empty_secs", str(leave_if_empty_secs),
        "--headless", str(headless).lower(),
    ]
    if start_time:
        cmd += ["--start_time", start_time]

    proc = subprocess.Popen(cmd)
    job_manager.add(job_id, proc)
    proc.wait()

    status = "finished" if proc.returncode == 0 else "error"
    try:
        audio = _find_audio(out_dir)
        transcript = transcribe_audio(audio) if audio else "No audio file found."
    except Exception as e:
        transcript = f"Transcription failed: {e}"

    # sync‑safe update
    def _update_sync():
        import anyio
        async def inner():
            await Job.find_one(Job.job_id == job_id).update({
                "$set": {
                    "status": status,
                    "finished_at": datetime.utcnow(),
                    "transcript": transcript,
                }
            })
        anyio.from_thread.run(inner)
    _update_sync()

# ─────────────────────────────────────────────── endpoints
@router.post("/start", summary="Start a Zoom bot job")
async def start_zoombot(req: ZoomBotJobRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex
    out_dir = os.path.abspath(os.path.join(req.save_dir, f"meeting_{job_id}"))

    # schedule sanity
    if req.start_time:
        dt = datetime.fromisoformat(req.start_time)
        if dt.tzinfo is None:
            dt = pytz.timezone("Asia/Karachi").localize(dt)
        if dt.astimezone(pytz.UTC) < datetime.utcnow().replace(tzinfo=pytz.UTC):
            raise HTTPException(400, "Scheduled time is in the past")

    await Job(
        job_id=job_id,
        email=req.email,
        meeting_url=f"zoom:{req.meeting_id}",   # keeps same field name
        status="pending",
        params=req.dict(),
        save_dir=out_dir,
    ).insert()

    await Job.find_one(Job.job_id == job_id).update({
        "$set": {"status": "running", "started_at": datetime.utcnow()}
    })

    bg.add_task(
        _run_zoom_bot_threaded,
        email=req.email,
        meeting_id=req.meeting_id,
        passcode=req.passcode,
        name=req.name,
        duration=req.duration,
        interval=req.interval,
        save_dir=out_dir,
        window_width=req.window_width,
        window_height=req.window_height,
        leave_if_empty_secs=req.leave_if_empty_secs,
        start_time=req.start_time,
        job_id=job_id,
        headless=req.headless,
    )
    return {"message": "Zoom bot started in background", "job_id": job_id}

@router.post("/cancel/{job_id}", summary="Cancel a Zoom bot job")
async def cancel_zoombot(job_id: str = Path(...)):
    if job_manager.cancel(job_id):
        await Job.find_one(Job.job_id == job_id).update({
            "$set": {"status": "cancelled", "finished_at": datetime.utcnow()}
        })
        return {"message": f"Job {job_id} cancelled"}
    raise HTTPException(404, "Job not found or already finished")

@router.get("/status/{job_id}", summary="Get Zoom bot job status")
async def zoombot_status(job_id: str):
    job = await Job.find_one(Job.job_id == job_id)
    return {"job_id": job_id, "status": job.status if job else "not_found"}

@router.get("/list", summary="List all Zoom bot jobs")
async def list_zoombot_jobs():
    jobs = await Job.find_all().to_list()
    return [
        {
            "job_id": j.job_id,
            "status": j.status,
            "email": j.email,
            "meeting_url": j.meeting_url,
            "save_dir": j.save_dir,
            "transcript": getattr(j, "transcript", None),
        } for j in jobs
    ]

@router.get("/info/{job_id}", summary="Get Zoom bot job details")
async def get_zoombot_info(job_id: str):
    job = await Job.find_one(Job.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job_id": job.job_id,
        "email": job.email,
        "meeting_url": job.meeting_url,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration": job.params.get("duration") if job.params else None,
        "save_dir": job.save_dir,
        "transcript": getattr(job, "transcript", None),
    }
