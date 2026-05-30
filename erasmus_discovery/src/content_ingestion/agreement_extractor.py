import os
from typing import Any, Dict, List

from ..services.gemini_client import DEFAULT_GEMINI_MODEL, call_gemini_json
from ..utils import truncate


MAX_EXTRACTION_CHARS = 35000


def agreement_extraction_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "agreements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "home_university_key": {"type": "string"},
                        "home_university": {"type": "string"},
                        "department": {"type": "string"},
                        "partner_university": {"type": "string"},
                        "partner_country": {"type": "string"},
                        "deadline": {"type": "string"},
                        "academic_year": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "evidence_text": {"type": "string"},
                    },
                    "required": [
                        "home_university_key",
                        "home_university",
                        "department",
                        "partner_university",
                        "partner_country",
                        "deadline",
                        "academic_year",
                        "confidence",
                        "evidence_text",
                    ],
                },
            }
        },
        "required": ["agreements"],
    }


def extract_agreements_with_gemini(
    cleaned_content: str,
    source_url: str,
    home_university_key: str,
    home_university: str,
    model: str | None = None,
) -> List[Dict[str, Any]]:
    prompt = f"""
Extract student Erasmus partner agreements from this cleaned source.

Rules:
- Return only actual student Erasmus partner agreements.
- Do not extract staff, teaching, training, faculty, or administrative mobility agreements.
- Do not create a row unless partner_university is clearly present.
- Do not invent partner universities, countries, departments, deadlines, or academic years.
- Missing fields must be empty strings.
- Do not write placeholders such as "Unspecified", "N/A", "Not provided", or "Unknown".
- Evidence text must contain only details present in the source; omit missing details from evidence.
- Evidence text must be in English. Translate Greek country names or surrounding words when needed.
- partner_university must contain only the institution name. Put Erasmus codes in evidence_text, not partner_university.
- partner_country must be the English country name, not an all-caps table value when a normal country name is clear.
- If no student partner agreements are found, return {{"agreements": []}}.
- Evidence text must be a short exact or near-exact source phrase that supports the row.
- Confidence high/medium/low should reflect how clearly the source states the row.
- Return strict JSON only.

Home university key: {home_university_key}
Home university: {home_university}
Source URL: {source_url}

Cleaned content:
{_fit_text(cleaned_content)}
"""
    result = call_gemini_json(
        prompt,
        schema=agreement_extraction_schema(),
        model=model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        timeout_seconds=180,
        system_prompt=(
            "You extract factual student Erasmus partner agreements. "
            "You never extract staff-only agreements and never invent missing values."
        ),
    )
    if result.get("error"):
        raise RuntimeError(result.get("message") or result.get("error"))
    agreements = result.get("agreements", [])
    if not isinstance(agreements, list):
        return []
    return [item for item in agreements if isinstance(item, dict)]


def _fit_text(text: str) -> str:
    text = text or ""
    if len(text) <= MAX_EXTRACTION_CHARS:
        return text
    head = truncate(text[:26000], 26000)
    tail = truncate(text[-8000:], 8000)
    return f"{head}\n\n[Middle content omitted because the source was very long.]\n\n{tail}"
