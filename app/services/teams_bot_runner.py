# app/services/teams_bot_runner.py

import os
import time
import subprocess
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError
from dotenv import load_dotenv

load_dotenv()
MS_EMAIL = os.getenv("MS_EMAIL")
MS_PASSWORD = os.getenv("MS_PASSWORD")

def wait_until(start_time_str: str):
    """Wait until the specified ISO8601 time (local or with TZ)."""
    if not start_time_str:
        return
    try:
        import pytz
        start_dt = datetime.fromisoformat(start_time_str)
        if start_dt.tzinfo is None:
            start_dt = pytz.timezone("Asia/Karachi").localize(start_dt)
        now_utc = datetime.now(timezone.utc)
        wait_seconds = (start_dt.astimezone(timezone.utc) - now_utc).total_seconds()
        if wait_seconds > 0:
            print(f"⏳ Waiting {wait_seconds/60:.1f} minutes until scheduled start time ({start_dt.isoformat()})...")
            time.sleep(wait_seconds)
        else:
            print("⚠️ Scheduled time is in the past or now; running immediately.")
    except Exception:
        print("Invalid --start_time argument, ignoring.")

def join_teams_and_capture(
    meeting_url: str,
    duration: int,
    interval: int,
    save_dir: str = "storage",
    window_size: tuple = (1280, 720),
    leave_if_empty_secs: int = 30,
    headless: bool = True,
):
    meeting_code = meeting_url.split("/")[-1].split("?")[0]
    out_dir = os.path.join(save_dir, f"teams_{meeting_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": window_size[0], "height": window_size[1]},
            permissions=["microphone", "camera"]
        )
        page = context.new_page()
        print("Navigating to Teams meeting...")
        page.goto(meeting_url)
        time.sleep(2)

        # Dismiss native popup if not headless (system modal)
        if not headless:
            try:
                import pyautogui
                time.sleep(2)
                pyautogui.press('esc')
                print("Sent ESC key to dismiss native system modal.")
            except Exception as e:
                print(f"pyautogui ESC not sent: {e}")

        # Click "Continue on this browser"
        try:
            page.click('text=Continue on this browser', timeout=10000)
            print("Clicked: Continue on this browser")
        except Exception:
            print("Could not find 'Continue on this browser' button, may have auto-redirected.")

        time.sleep(2)

        # Fill guest name (robust with multiple selectors)
        name_selectors = [
            'input[placeholder="Type your name"]',
            'input[data-tid="prejoin-display-name-input"]',
            'input[aria-label="Type your name"]',
            '.fui-Input input[type="text"]',
        ]
        name_filled = False
        for selector in name_selectors:
            try:
                page.wait_for_selector(selector, timeout=3000)
                page.fill(selector, "MinuteMate Bot")
                print(f"Filled guest name using selector: {selector}")
                name_filled = True
                break
            except Exception:
                continue
        if not name_filled:
            print("Could NOT fill guest name! Check selectors and page structure.")
        # Debug screenshot after name fill
        page.screenshot(path=os.path.join(out_dir, "after_fill_name.png"))

        time.sleep(2)

        # Handle "Continue without audio or video" modal
        try:
            btn_selector = 'button:has-text("Continue without audio or video")'
            page.wait_for_selector(btn_selector, timeout=7000)
            page.click(btn_selector)
            print("Clicked 'Continue without audio or video'.")
            time.sleep(2)
        except TimeoutError:
            print("No modal about audio/video appeared.")
        except Exception as e:
            print(f"Failed to click 'Continue without audio or video': {e}")

        # Mute mic/cam if available
        for selector, desc in [
            ('button[title="Mute microphone"]', "Muted microphone."),
            ('button[title="Turn camera off"]', "Turned camera off.")
        ]:
            try:
                page.click(selector, timeout=4000)
                print(desc)
            except Exception:
                pass

        # Click "Join now"
        try:
            page.wait_for_selector('button:has-text("Join now")', timeout=15000)
            page.click('button:has-text("Join now")')
            print("Joined the Teams meeting!")
            time.sleep(2)
        except Exception as e:
            print(f"Could not join meeting: {e}")

        # Start audio recording
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = os.path.join(out_dir, f"teams_audio_{timestamp}.wav")
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

        print(f"Starting screenshots: every {interval}s for up to {duration}s")
        try:
            time.sleep(1)
            while time.time() - start_time < duration:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"teams_screenshot_{screenshot_count}_{timestamp}.png"
                filepath = os.path.join(out_dir, filename)
                try:
                    page.screenshot(path=filepath)
                    print(f"Saved screenshot: {filepath}")
                except Exception as e:
                    print(f"Screenshot failed: {e}")
                screenshot_count += 1
                time.sleep(interval)
        finally:
            ffmpeg_proc.terminate()
            try:
                ffmpeg_proc.wait(timeout=10)
            except Exception:
                ffmpeg_proc.kill()
            # Try to leave meeting before closing
            try:
                leave_clicked = False
                for selector in [
                    'button[title="Leave"]',
                    'button:has-text("Leave")',
                    'button[data-tid="call-hangup"]'
                ]:
                    if page.locator(selector).is_visible(timeout=2000):
                        page.click(selector)
                        print("Clicked Leave button.")
                        time.sleep(2)
                        leave_clicked = True
                        break
                if not leave_clicked:
                    print("Leave button not found (possibly in waiting room or already left).")
            except Exception as e:
                print(f"Could not click Leave: {e}")
            context.close()
            browser.close()
            print("Teams bot finished!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--meeting_url", type=str, required=True)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--save_dir", type=str, default="storage")
    parser.add_argument("--window_width", type=int, default=1280)
    parser.add_argument("--window_height", type=int, default=720)
    parser.add_argument("--leave_if_empty_secs", type=int, default=30)
    parser.add_argument("--headless", type=str, default="true")
    parser.add_argument("--start_time", type=str, default=None, help="Scheduled start time (ISO8601, e.g. 2025-07-30T16:07:00+05:00)")
    args = parser.parse_args()
    headless = args.headless.lower() != "false"

    # Wait until --start_time if provided
    wait_until(args.start_time)

    join_teams_and_capture(
        meeting_url=args.meeting_url,
        duration=args.duration,
        interval=args.interval,
        save_dir=args.save_dir,
        window_size=(args.window_width, args.window_height),
        leave_if_empty_secs=args.leave_if_empty_secs,
        headless=headless
    )
