from __future__ import annotations

from typing import List

import requests

from ..config import GEMINI_ENDPOINT_TEMPLATE, GEMINI_MODEL, get_gemini_keys


class GeminiError(RuntimeError):
    pass


def call_gemini(prompt: str, timeout_seconds: int = 60) -> str:
    keys = get_gemini_keys()
    if not keys:
        raise GeminiError("GEMINI_API_KEY is not configured.")

    endpoint = GEMINI_ENDPOINT_TEMPLATE.format(model=GEMINI_MODEL)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "maxOutputTokens": 1400,
        },
    }

    last_error = ""
    for index, key in enumerate(keys):
        try:
            response = requests.post(
                endpoint,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=payload,
                timeout=timeout_seconds,
            )
            if response.status_code == 429 and index < len(keys) - 1:
                last_error = "Gemini key quota exceeded; trying next configured key."
                continue
            response.raise_for_status()
            return _output_text(response.json()).strip()
        except requests.RequestException as exc:
            last_error = str(exc)
            if index < len(keys) - 1:
                continue
            break

    raise GeminiError(last_error or "Gemini request failed.")


def _output_text(data: dict) -> str:
    candidates: List[dict] = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(str(part.get("text", "")) for part in parts if part.get("text"))
