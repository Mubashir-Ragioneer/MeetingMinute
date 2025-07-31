# /app/services/meet_bot_runner.py

import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError
from dotenv import load_dotenv

load_dotenv()

def wait_until(iso_ts: Optional[str]) -> None:
    if not iso_ts:
        return
    try:
        import pytz
        start_dt = datetime.fromisoformat(iso_ts)
        if start_dt.tzinfo is None:
            start_dt = pytz.timezone("Asia/Karachi").localize(start_dt)
        wait_s = (start_dt.astimezone().timestamp() - datetime.now().timestamp())
        if wait_s > 0:
            print(f"⏳ Waiting {wait_s/60:.1f} min until {start_dt.isoformat()} …")
            time.sleep(wait_s)
        else:
            print("⚠️ Scheduled time already passed; running now.")
    except Exception:
        print("Invalid --start_time provided; ignoring.")

def wait_for_name_input(page, timeout=60):
    """
    Wait for 'Your name' input or join as guest UI, try reloads, and save a debug screenshot if it never appears.
    Returns the element handle if found, else None.
    """
    start = time.time()
    tried_reload = False
    while time.time() - start < timeout:
        # Try to get the name input (typical guest flow)
        try:
            input_box = page.query_selector('input[type="text"][aria-label="Your name"]')
            if input_box and input_box.is_visible():
                return input_box
        except Exception:
            pass
        # Try to get a "join as guest" button (sometimes Google adds this step)
        try:
            guest_btn = page.query_selector('button:has-text("Join as guest")')
            if guest_btn and guest_btn.is_visible():
                print("Clicking 'Join as guest' button...")
                guest_btn.click()
                time.sleep(2)
                continue  # Try for name input again
        except Exception:
            pass
        # If input not found, sometimes a reload helps in headless mode!
        if not tried_reload and time.time() - start > 10:
            print("Input not found after 10s, reloading page (headless anti-bot workaround)...")
            page.reload(wait_until="domcontentloaded")
            tried_reload = True
            time.sleep(2)
            continue
        time.sleep(1)
    return None

def join_meet(
    *,
    meeting_url: str,
    name: str = "MinuteMate Bot",
    duration: int = 120,
    interval: int = 10,
    save_dir: str = "storage",
    window_size: tuple[int, int] = (1280, 720),
    headless: bool = True,
    admit_timeout: int = 300,   # How long (seconds) to wait to be admitted to the meeting
):
    code = meeting_url.split('/')[-1]
    out_dir = Path(save_dir) / f"meet_{code}_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                f"--window-size={window_size[0]},{window_size[1]}",
                "--start-maximized",
                "--ignore-certificate-errors",
                "--lang=en-US,en",
                "--use-fake-ui-for-media-stream"
            ],
        )
        context = browser.new_context(
            viewport={"width": window_size[0], "height": window_size[1]},
            permissions=["microphone", "camera"],
            locale="en-US"
        )
        page = context.new_page()

        print(f"Navigating to Google Meet: {meeting_url}")
        page.goto(meeting_url, wait_until="domcontentloaded")

        # Robust: wait for the name input or guest button with reload/retry
        name_box = wait_for_name_input(page, timeout=60)
        if not name_box:
            debug_path = out_dir / "debug_failed_headless.png"
            page.screenshot(path=debug_path)
            debug_html_path = out_dir / "debug_failed_headless.html"
            page_content = page.content()
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(page_content)
            print(f"ERROR: Name input not found! Screenshot at {debug_path}, HTML at {debug_html_path}")
            raise RuntimeError("Failed to find 'Your name' input (even after reload) in headless/headed mode.")

        try:
            name_box.fill(name)
            print(f"Filled in name: {name}")
        except Exception as e:
            debug_path = out_dir / "debug_failed_fillname.png"
            page.screenshot(path=debug_path)
            print(f"ERROR: Could not fill name. Screenshot at {debug_path}")
            raise RuntimeError(f"Failed to fill guest name: {e}")

        # Click "Ask to join"
        try:
            page.wait_for_selector('button:has-text("Ask to join")', timeout=20_000)
            page.click('button:has-text("Ask to join")')
            print("Clicked 'Ask to join'.")
        except Exception as e:
            debug_path = out_dir / "debug_failed_asktojoin.png"
            page.screenshot(path=debug_path)
            print(f"ERROR: 'Ask to join' button not found/clickable. Screenshot: {debug_path}")
            raise RuntimeError(f"Failed to click 'Ask to join' button: {e}")

        print("Waiting to be admitted to the meeting...")

        # Wait for the "Leave call" button to appear (admitted = in the meeting)
        start_wait = time.time()
        admitted = False
        while time.time() - start_wait < admit_timeout:
            try:
                if page.query_selector('button[aria-label="Leave call"]'):
                    admitted = True
                    print("Admitted to meeting!")
                    break
            except Exception:
                pass
            time.sleep(2)
        if not admitted:
            print(f"Never admitted to the meeting within {admit_timeout//60} minutes. Exiting.")
            context.close()
            browser.close()
            return

        # Now start the audio recording and screenshots!
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = out_dir / f"meet_audio_{ts}.wav"
        ffmpeg_log = open(out_dir / "ffmpeg_audio.log", "w", encoding="utf-8")
        ffmpeg = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-f", "dshow",      # for Windows, change to "-f", "avfoundation" on Mac
                "-i", "audio=Stereo Mix (Realtek(R) Audio)",   # system default device, change if needed
                "-t", str(duration),
                str(audio_path),
            ],
            stdout=ffmpeg_log,
            stderr=ffmpeg_log,
        )
        print(f"Recording audio from default system device → {audio_path.name} | screenshots every {interval}s")

        # Screenshot loop
        start = time.time()
        shot = 0
        try:
            while time.time() - start < duration:
                snap_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                snap_path = out_dir / f"meet_screenshot_{shot}_{snap_ts}.png"
                page.screenshot(path=snap_path)
                print(f"✓ {snap_path.name}")
                shot += 1
                time.sleep(interval)
        finally:
            ffmpeg.terminate()
            try:
                ffmpeg.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ffmpeg.kill()
            ffmpeg_log.close()
            context.close()
            browser.close()
            print("Meet bot finished!")

    return out_dir

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--meeting_url", required=True)
    parser.add_argument("--name", default="MinuteMate Bot")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--save_dir", default="storage")
    parser.add_argument("--window_width", type=int, default=1280)
    parser.add_argument("--window_height", type=int, default=720)
    parser.add_argument("--headless", default="true")
    parser.add_argument("--start_time", help="ISO‑8601 start (e.g. 2025-07-30T16:07:00+05:00)")
    parser.add_argument("--admit_timeout", type=int, default=300, help="Max seconds to wait for being admitted to the meeting")
    args = parser.parse_args()
    headless_bool = args.headless.lower() != "false"

    wait_until(args.start_time)

    join_meet(
        meeting_url=args.meeting_url,
        name=args.name,
        duration=args.duration,
        interval=args.interval,
        save_dir=args.save_dir,
        window_size=(args.window_width, args.window_height),
        headless=headless_bool,
        admit_timeout=args.admit_timeout,
    )
