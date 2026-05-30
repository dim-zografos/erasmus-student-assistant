import os
from typing import Any, Dict

from ..services.gemini_client import DEFAULT_GEMINI_MODEL, call_gemini_json
from ..utils import truncate


MAX_NORMALIZATION_CHARS = 30000


def normalization_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "store_document": {"type": "boolean"},
            "skip_reason": {"type": "string"},
            "document_type": {"type": "string"},
            "title": {"type": "string"},
            "cleaned_content": {"type": "string"},
            "key_topics": {"type": "array", "items": {"type": "string"}},
            "contains_agreements": {"type": "boolean"},
            "contains_deadlines": {"type": "boolean"},
            "contains_requirements": {"type": "boolean"},
        },
        "required": [
            "store_document",
            "skip_reason",
            "document_type",
            "title",
            "cleaned_content",
            "key_topics",
            "contains_agreements",
            "contains_deadlines",
            "contains_requirements",
        ],
    }


def normalize_document_with_gemini(
    raw_text: str,
    source_url: str,
    title: str,
    category: str,
    model: str | None = None,
) -> Dict[str, Any]:
    prompt = f"""
Clean and organize this Erasmus source document for storage.

Rules:
- Output English only. Translate Greek or other languages into English.
- Preserve factual details from the source.
- Do not invent universities, countries, departments, deadlines, years, requirements, or links.
- If something is unclear, omit it or keep it clearly marked as unclear.
- Remove menus, repeated navigation, cookie text, and duplicated boilerplate.
- Keep useful Erasmus information, deadlines, application requirements, partner/agreement information, and evidence-like text.
- Do not summarize so aggressively that important names, dates, countries, departments, or requirements disappear.
- Decide whether the cleaned document should be stored.
- Set store_document=true if the source contains any useful public Erasmus fact, even if the content is short.
- Set store_document=false only when the source is cookie-only, navigation-only, title-only, duplicate-empty, access-restricted, broken, or has no factual Erasmus content.
- Do not set store_document=false only because the useful content is short.
- If store_document=false, leave cleaned_content empty or minimal and explain the issue in skip_reason.
- If store_document=true, skip_reason must be an empty string.
- Set contains_agreements=true only when the source appears to contain bilateral, inter-institutional, or partner-university agreement records.
- Do not set contains_agreements=true only because the text mentions a traineeship host, receiving organization, learning agreement, application form, or general partner institution concept.
- Return strict JSON only.

Source URL: {source_url}
Selected title: {title}
Selected category: {category}

Extracted text:
{_fit_text(raw_text)}
"""
    result = call_gemini_json(
        prompt,
        schema=normalization_schema(),
        model=model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        timeout_seconds=180,
        system_prompt=(
            "You clean university Erasmus source text for a factual dataset. "
            "You translate to English and never invent missing values."
        ),
    )
    if result.get("error"):
        raise RuntimeError(result.get("message") or result.get("error"))
    result["store_document"] = bool(result.get("store_document", True))
    result["skip_reason"] = str(result.get("skip_reason") or "").strip()
    result["title"] = str(result.get("title") or title or "")
    result["document_type"] = str(result.get("document_type") or category or "general_erasmus_information")
    result["cleaned_content"] = str(result.get("cleaned_content") or "").strip()
    if not isinstance(result.get("key_topics"), list):
        result["key_topics"] = []
    return result


def _fit_text(text: str) -> str:
    text = text or ""
    if len(text) <= MAX_NORMALIZATION_CHARS:
        return text
    head = truncate(text[:22000], 22000)
    tail = truncate(text[-7000:], 7000)
    return f"{head}\n\n[Middle content omitted because the source was very long.]\n\n{tail}"
