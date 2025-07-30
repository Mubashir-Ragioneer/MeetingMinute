# app/services/zoom_bot_runner.py
"""
Autonomous guest bot for the Zoom Web Client.

Example (Windows host with a valid loop‑back capture device):

    python app/services/zoom_bot_runner.py \
        --meeting_id 81351987305 \
        --passcode 1KubmB \
        --name "MinuteMate Bot" \
        --duration 120 \
        --interval 10 \
        --audio_device "Stereo Mix (Realtek(R) Audio)" \
        --headless false
"""
import sys
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError
from dotenv import load_dotenv

load_dotenv()

# ───────────────────────────────────────────────────────── helpers
def wait_until(iso_ts: Optional[str]) -> None:
    """Sleep until the ISO‑8601 timestamp given (assume Asia/Karachi if TZ omitted)."""
    if not iso_ts:
        return
    try:
        import pytz

        start_dt = datetime.fromisoformat(iso_ts)
        if start_dt.tzinfo is None:  # naive → Asia/Karachi
            start_dt = pytz.timezone("Asia/Karachi").localize(start_dt)

        wait_s = (start_dt.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        if wait_s > 0:
            print(f"⏳ Waiting {wait_s/60:.1f} min until {start_dt.isoformat()} …")
            time.sleep(wait_s)
        else:
            print("⚠️ Scheduled time already passed; running now.")
    except Exception:
        print("Invalid --start_time provided; ignoring.")


# ───────────────────────────────────────────────────────── main worker
def join_zoom_meeting(
    *,
    meeting_id: str,
    passcode: str,
    name: str = "MinuteMate Bot",
    duration: int = 120,
    interval: int = 10,
    save_dir: str = "storage",
    window_size: tuple[int, int] = (1280, 720),
    headless: bool = True,
    leave_if_empty_secs: int = 30,
    audio_device: str = "Stereo Mix (Realtek(R) Audio)",
):
    """
    * Navigates to https://app.zoom.us/wc/join
    * Joins as guest, clicks “Continue without microphone and camera” twice
    * Switches into <iframe id="webclient"> to fill passcode & name
    * Records audio & screenshots for `duration` seconds
    """
    out_dir = (
        Path(save_dir)
        / f"zoom_{meeting_id}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": window_size[0], "height": window_size[1]},
            permissions=["microphone", "camera"],
        )
        page = context.new_page()

        # 1️⃣ Join page + Meeting‑ID
        print("Navigating to Zoom join page …")
        page.goto("https://app.zoom.us/wc/join", wait_until="domcontentloaded")
        page.fill('input[placeholder="Meeting ID or Personal Link Name"]', meeting_id)
        page.click('button:has-text("Join")')
        print("→ Meeting ID submitted.")

        # 2️⃣ Dismiss two “continue without mic/cam” pop‑ups (outer page)
        for _ in range(2):
            try:
                page.wait_for_selector(
                    'button:has-text("Continue without microphone and camera")',
                    timeout=10_000,
                ).click()
                print("→ Clicked 'Continue without microphone and camera'")
                time.sleep(1)
            except TimeoutError:
                break

        # 3️⃣ Locate the webclient iframe (contains actual form)
        frame = None
        for _ in range(20):
            frame = page.frame(name="webclient")
            if frame:
                break
            time.sleep(0.5)
        if not frame:
            raise RuntimeError("Could not locate Zoom webclient iframe; aborting.")

        # 4️⃣ Wait until passcode box exists inside the iframe
        frame.wait_for_selector(
            'input[placeholder="Meeting Passcode"], #input-for-pwd',
            timeout=20_000,
        )

        # 5️⃣ Fill passcode FIRST (Zoom hides name input until correct passcode)
        pwd_selectors = [
            'input[placeholder="Meeting Passcode"]',
            '#input-for-pwd',
            'input[type="password"]',
            'input[aria-label="Meeting Passcode"]',
        ]
        for sel in pwd_selectors:
            try:
                if frame.locator(sel).is_visible(timeout=2_000):
                    frame.fill(sel, passcode)
                    print("→ Filled passcode.")
                    break
            except Exception:
                continue
        else:
            raise RuntimeError("Could not fill passcode; selector not found.")

        # 6️⃣ Fill display name
        name_selectors = [
            'input[placeholder="Your Name"]',
            '#input-for-name',
            'input[aria-label="Your Name"]',
            'input[aria-label="Name"]',
        ]
        for sel in name_selectors:
            try:
                if frame.locator(sel).is_visible(timeout=2_000):
                    frame.fill(sel, name)
                    print("→ Filled display name.")
                    break
            except Exception:
                continue

        # 7️⃣ Click Join inside iframe
        try:
            frame.click('button:has-text("Join")')
            print("Joining meeting …")
        except Exception as e:
            raise RuntimeError(f"Could not click final Join: {e}") from e

        # 8️⃣ Start capture
        time.sleep(5)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = out_dir / f"zoom_audio_{ts}.wav"
        ffmpeg_log = open(out_dir / "ffmpeg_audio.log", "w", encoding="utf-8")
        ffmpeg = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-f", "dshow",
                "-i", f"audio={audio_device}",
                "-t", str(duration),
                str(audio_path),
            ],
            stdout=ffmpeg_log,
            stderr=ffmpeg_log,
        )
        print(
            f"Recording audio from '{audio_device}' → {audio_path.name} | screenshots every {interval}s"
        )

        start = time.time()
        shot = 0
        try:
            while time.time() - start < duration:
                snap_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                snap_path = out_dir / f"zoom_screenshot_{shot}_{snap_ts}.png"
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

            # attempt to leave meeting
            try:
                for sel in ('button[aria-label="Leave"]', 'button:has-text("Leave")'):
                    if frame.locator(sel).is_visible(timeout=2_000):
                        frame.click(sel)
                        print("→ Clicked Leave.")
                        break
            except Exception:
                pass

            context.close()
            browser.close()
            print("Zoom bot finished!")

    return out_dir


# ───────────────────────────────────────────────────────── CLI
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--meeting_id", required=True)
    parser.add_argument("--passcode", required=True)
    parser.add_argument("--name", default="MinuteMate Bot")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--save_dir", default="storage")
    parser.add_argument("--window_width", type=int, default=1280)
    parser.add_argument("--window_height", type=int, default=720)
    parser.add_argument("--headless", default="true")
    parser.add_argument(
        "--start_time",
        help="ISO‑8601 start (e.g. 2025-07-30T16:07:00+05:00)",
    )
    parser.add_argument("--leave_if_empty_secs", type=int, default=30)
    args = parser.parse_args()
    headless_bool = args.headless.lower() != "false"

    wait_until(args.start_time)

    join_zoom_meeting(
        meeting_id=args.meeting_id,
        passcode=args.passcode,
        name=args.name,
        duration=args.duration,
        interval=args.interval,
        save_dir=args.save_dir,
        window_size=(args.window_width, args.window_height),
        headless=headless_bool,
        leave_if_empty_secs=args.leave_if_empty_secs
    )



