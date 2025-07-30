# /app/services/transcribe.py

import openai
import os
import dotenv

dotenv.load_dotenv()

def transcribe_audio(audio_path, api_key=None):
    """
    Transcribe an audio file using OpenAI Whisper API.
    Returns the transcript text or an error string.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "OpenAI API key not provided"

    try:
        import requests

        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        files = {
            "file": (os.path.basename(audio_path), open(audio_path, "rb"), "audio/wav")
        }
        data = {
            "model": "whisper-1",
            "response_format": "text"
        }
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers=headers,
            files=files,
            data=data
        )
        if resp.status_code == 200:
            return resp.text.strip()
        else:
            return f"API error {resp.status_code}: {resp.text}"

    except Exception as e:
        return f"Transcription error: {e}"
