import os
import re
import time
import subprocess
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import asyncio
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models.user import User
from app.core.db import init_db

try:
    import pytz
except ImportError:
    raise ImportError("Please install pytz: pip install pytz")

load_dotenv()
GOOGLE_EMAIL = os.getenv("GOOGLE_EMAIL")
GOOGLE_PASSWORD = os.getenv("GOOGLE_PASSWORD")

def wait_until(start_time_str: str):
    if not start_time_str:
        return
    try:
        start_dt = datetime.fromisoformat(start_time_str)
    except Exception:
        raise ValueError(f"Invalid start_time format: {start_time_str}. Use ISO8601 like 2025-07-28T01:30:00+05:00")
    if start_dt.tzinfo is None:
        start_dt = pytz.timezone("Asia/Karachi").localize(start_dt)
    now_utc = datetime.now(timezone.utc)
    wait_seconds = (start_dt.astimezone(timezone.utc) - now_utc).total_seconds()
    if wait_seconds > 0:
        print(f"⏳ Waiting {wait_seconds/60:.1f} minutes until scheduled start time ({start_dt.isoformat()})...")
        time.sleep(wait_seconds)
    else:
        print("⚠️ Scheduled time is in the past or now; running immediately.")

async def get_user_full_name(email):
    await init_db()
    user = await User.find_one(User.email == email)
    if not user:
        raise Exception(f"User not found for email {email}")
    return user.full_name

def safe_folder_name(name: str) -> str:
    return re.sub(r'[^\w\-]', '_', name.strip())

def join_meet_and_capture(
    user_folder: str,
    meet_url: str,
    duration: int,
    interval: int,
    save_dir: str = "screenshots",
    window_size: tuple = (1280, 720),
    leave_if_empty_secs: int = 30
):
    if not GOOGLE_EMAIL or not GOOGLE_PASSWORD:
        raise ValueError("Google credentials not set in environment variables.")
    meeting_code = meet_url.rstrip('/').split('/')[-1]
    out_dir = os.path.join(save_dir, f"{user_folder}_{meeting_code}")
    os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': window_size[0], 'height': window_size[1]})
        page = context.new_page()

        print("Logging in to Google...")
        page.goto("https://accounts.google.com/signin/v2/identifier")
        page.fill('input[type="email"]', GOOGLE_EMAIL)
        page.click('button:has-text("Next")')
        page.wait_for_timeout(2000)
        page.fill('input[type="password"]', GOOGLE_PASSWORD)
        page.click('button:has-text("Next")')
        page.wait_for_timeout(5000)
        print("Logged in!")

        print(f"Navigating to meeting: {meet_url}")
        page.goto(meet_url)
        time.sleep(7)

        try:
            print("Checking for camera/mic permissions popup...")
            no_mic_cam_btn = page.locator('text=Continue without microphone and camera')
            if no_mic_cam_btn.is_visible(timeout=10000):
                no_mic_cam_btn.click()
                print("Clicked 'Continue without microphone and camera'")
        except Exception as e:
            print(f"Popup not found or error: {e}")

        try:
            join_btn = page.locator('text="Join now"')
            if join_btn.is_visible(timeout=15000):
                join_btn.click()
                print("Joined the meeting!")
        except Exception as e:
            print(f"Could not auto-join. Error: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = os.path.join(out_dir, f"meeting_audio_{timestamp}.wav")
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f", "dshow",
            "-i", "audio=Stereo Mix (Realtek(R) Audio)",
            "-t", str(duration),
            audio_path,
        ]
        ffmpeg_proc = subprocess.Popen(ffmpeg_cmd)

        start_time = time.time()
        screenshot_count = 0
        last_seen_participant = start_time
        print(f"Starting screenshots: every {interval}s for up to {duration}s (leave if empty for {leave_if_empty_secs}s)")

        try:
            while time.time() - start_time < duration:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{screenshot_count}_{timestamp}.png"
                filepath = os.path.join(out_dir, filename)
                try:
                    page.screenshot(path=filepath)
                    print(f"Saved screenshot: {filepath}")
                except Exception as e:
                    print(f"Screenshot failed: {e}")

                try:
                    only_you_msg = page.locator('text=You are the only one here')
                    if only_you_msg.is_visible():
                        print("Detected: You are the only one here!")
                        if time.time() - last_seen_participant > leave_if_empty_secs:
                            print(f"No one else joined for {leave_if_empty_secs} seconds. Leaving meeting.")
                            break
                    else:
                        last_seen_participant = time.time()
                except Exception as e:
                    print(f"Attendance check error: {e}")

                screenshot_count += 1
                time.sleep(interval)
        finally:
            ffmpeg_proc.terminate()
            try:
                ffmpeg_proc.wait(timeout=10)
            except Exception:
                ffmpeg_proc.kill()
            browser.close()
            print("All done!")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--email", type=str, required=True)
    parser.add_argument("--meeting_url", type=str, required=True)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--save_dir", type=str, default="screenshots")
    parser.add_argument("--window_width", type=int, default=1280)
    parser.add_argument("--window_height", type=int, default=720)
    parser.add_argument("--leave_if_empty_secs", type=int, default=30)
    parser.add_argument("--start_time", type=str, default=None, help="Scheduled start time (e.g. 2025-07-28T01:30:00+05:00)")
    args = parser.parse_args()

    wait_until(args.start_time)

    # --- Get user full name as folder name ---
    user_full_name = safe_folder_name(asyncio.run(get_user_full_name(args.email)))

    join_meet_and_capture(
        user_folder=user_full_name,
        meet_url=args.meeting_url,
        duration=args.duration,
        interval=args.interval,
        save_dir=args.save_dir,
        window_size=(args.window_width, args.window_height),
        leave_if_empty_secs=args.leave_if_empty_secs,
    )
