"""AssemblyAI transcription helpers."""
import time
import requests
from django.conf import settings


class AssemblyAIClient:
    def __init__(self):
        self.api_key = settings.ASSEMBLYAI_API_KEY
        self.base_url = "https://api.assemblyai.com/v2"

    def _headers(self):
        return {
            "authorization": self.api_key,
            "content-type": "application/json"
        }

    def start_transcription(self, audio_url):
        payload = {
            "audio_url": audio_url,
            "language_detection": True
        }
        response = requests.post(f"{self.base_url}/transcript", json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()

    def get_transcription(self, transcript_id):
        response = requests.get(f"{self.base_url}/transcript/{transcript_id}", headers=self._headers())
        response.raise_for_status()
        return response.json()

    def wait_for_transcription(self, transcript_id, timeout_seconds=60, poll_interval=3):
        start = time.time()
        while time.time() - start < timeout_seconds:
            data = self.get_transcription(transcript_id)
            status = data.get("status")
            if status in ("completed", "failed"):
                return data
            time.sleep(poll_interval)
        return {"status": "processing"}
