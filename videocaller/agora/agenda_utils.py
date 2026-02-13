import logging
import re
from typing import List
import requests
from django.conf import settings
from .embedding_utils import search_similar_chunks

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = getattr(settings, 'GOOGLE_API_KEY', '')
GOOGLE_GENERATE_MODEL = getattr(settings, 'GOOGLE_GENERATE_MODEL', 'gemini-2.5-flash-lite')
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
GOOGLE_CONNECT_TIMEOUT = getattr(settings, 'GOOGLE_CONNECT_TIMEOUT', 10)
GOOGLE_READ_TIMEOUT = getattr(settings, 'GOOGLE_READ_TIMEOUT', 600)


def _google_generate(prompt: str) -> str:
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not configured")

    url = f"{GOOGLE_API_BASE}{GOOGLE_GENERATE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    response = requests.post(
        url,
        json=payload,
        timeout=(GOOGLE_CONNECT_TIMEOUT, GOOGLE_READ_TIMEOUT)
    )
    response.raise_for_status()
    data = response.json()

    text_parts: List[str] = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            part_text = part.get("text")
            if part_text:
                text_parts.append(part_text)
    return "".join(text_parts).strip()


def _parse_points(text: str, max_points: int = 8) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    points: List[str] = []
    for line in lines:
        cleaned = re.sub(r"^[\-\*•\.\d\)\(]+\s*", "", line).strip()
        if cleaned:
            points.append(cleaned)
        if len(points) >= max_points:
            break
    if not points and text.strip():
        points = [text.strip()]
    return points


def generate_agenda_points(meeting_title: str, meeting_description: str, meeting_id: int | None) -> List[str]:
    agenda_hint = (meeting_title or "").strip()
    query = f"Agenda: {agenda_hint}" if agenda_hint else "meeting agenda"
    relevant_chunks = search_similar_chunks(query, meeting_id, top_k=12)
    if not relevant_chunks:
        return []

    context = "\n\n".join([
        f"[Source: {chunk.get('source_type', 'meeting_transcript')}] {chunk['text']}"
        for chunk in relevant_chunks
    ])

    prompt = (
        "You are preparing concise discussion points for a meeting.\n"
        "Use ONLY the PAST NOTES below. Do not add new information or assumptions.\n"
        "If the notes do not support a point, do not include it.\n"
        "Return 5-8 short points (max 14 words each), one per line, no numbering.\n\n"
        f"MEETING TITLE: {agenda_hint or 'N/A'}\n\n"
        f"PAST NOTES:\n{context}"
    )

    try:
        raw = _google_generate(prompt)
        points = _parse_points(raw)
        return points
    except Exception as e:
        logger.error("Error generating agenda points: %s", str(e))
        return []
