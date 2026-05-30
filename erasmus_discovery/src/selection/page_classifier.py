import os
import time
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from ..core.models import UrlClassification
from ..services.gemini_client import (
    DEFAULT_GEMINI_MODEL,
    call_gemini_json,
    has_gemini_key,
    url_classification_schema,
)
from ..storage.database import get_candidate_urls, log_event, upsert_url_classification
from ..utils import is_pdf_resource, json_loads_list, truncate
from .page_metadata import fetch_page_metadata


ALLOWED_CATEGORIES = {
    "agreements",
    "partner_universities",
    "outgoing_studies",
    "deadlines",
    "application_requirements",
    "learning_agreement",
    "traineeship",
    "general_erasmus_information",
    "irrelevant",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _metadata_text(metadata: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(metadata.get("title") or ""),
            str(metadata.get("meta_description") or ""),
            str(metadata.get("meta_keywords") or ""),
            " ".join(str(item) for item in metadata.get("headings", []) or []),
            str(metadata.get("snippet") or ""),
        ]
    ).lower()


def _is_staff_teaching_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(
        term in lowered
        for term in [
            "staff",
            "teaching",
            "teacher",
            "faculty",
            "didaskonton",
            "prosopik",
            "kinhtikothta-proswpik",
            "kinitikotita-prosopik",
        ]
    )


def _looks_staff_only(metadata: Dict[str, Any]) -> bool:
    text = _metadata_text(metadata)
    staff_indicators = [
        "staff mobility",
        "teaching staff",
        "teacher mobility",
        "teachers mobility",
        "faculty members",
        "academic staff",
        "κινητικότητα προσωπικ",
        "διδασκαλ",
        "διδακτικ",
    ]
    student_indicators = ["student", "students", "traineeship", "studies", "φοιτη", "σπουδ"]
    return any(term in text for term in staff_indicators) and not any(term in text for term in student_indicators)


def _looks_event_only(metadata: Dict[str, Any]) -> bool:
    text = _metadata_text(metadata)
    event_indicators = [
        "lecture",
        "workshop",
        "seminar",
        "event",
        "guest speaker",
        "webinar",
        "conference",
        "διάλεξ",
        "εργαστήρ",
        "σεμινάρ",
        "ημερίδ",
        "εκδήλωσ",
    ]
    durable_info_indicators = [
        "application",
        "deadline",
        "requirements",
        "learning agreement",
        "partner",
        "agreement",
        "outgoing studies",
        "incoming students",
        "student mobility",
        "traineeship",
        "αίτησ",
        "αιτήσ",
        "προθεσμ",
        "δικαιολογ",
        "συμφων",
        "σπουδ",
        "πρακτικ",
    ]
    return any(term in text for term in event_indicators) and not any(
        term in text for term in durable_info_indicators
    )


def _rejected_classification(row, reason: str, metadata: Optional[Dict[str, Any]] = None) -> UrlClassification:
    metadata = metadata or {}
    return UrlClassification(
        university_key=row["university_key"],
        base_url_id=row["base_url_id"] or 0,
        url=row["url"],
        title=str(metadata.get("title") or row["title"] or ""),
        snippet=truncate(str(metadata.get("snippet") or ""), 500),
        selected=False,
        category="irrelevant",
        relevance_score=0,
        reason=reason,
        expected_data=[],
        priority="low",
    )


def _prepare_item(row) -> UrlClassification | Dict[str, Any]:
    if _is_staff_teaching_url(row["url"]):
        return _rejected_classification(
            row,
            "Rejected because the URL is a staff/teaching agreement page, not a student Erasmus agreement page.",
        )

    metadata = fetch_page_metadata(row["url"])
    if is_pdf_resource(row["url"]) and not metadata.get("title") and row["title"]:
        metadata["title"] = row["title"]
    if _looks_staff_only(metadata):
        return _rejected_classification(
            row,
            "Rejected because the source appears to be staff/faculty teaching mobility without student Erasmus information.",
            metadata,
        )
    if _looks_event_only(metadata):
        return _rejected_classification(
            row,
            "Rejected because the source appears to be a one-off Erasmus event/news item without durable student Erasmus information.",
            metadata,
        )
    return {"row": row, "metadata": metadata}


def _compact_item(index: int, row, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "n": index,
        "url": row["url"],
        "content_type": metadata.get("content_type") or row["content_type"] or "",
        "title": metadata.get("title") or row["title"] or "",
        "description": truncate(str(metadata.get("meta_description") or ""), 140),
        "keywords": truncate(str(metadata.get("meta_keywords") or ""), 160),
        "headings": (metadata.get("headings") or [])[:6],
        "snippet": truncate(str(metadata.get("snippet") or ""), 700),
        "matched_keywords": row["matched_keywords"] or "",
    }


def _build_batch_prompt(items: List[Dict[str, Any]]) -> str:
    compact_items = [_compact_item(index, item["row"], item["metadata"]) for index, item in enumerate(items, start=1)]
    return f"""
Classify these URLs for an Erasmus information discovery dataset.

Rules:
- Select useful student Erasmus pages, including general information.
- Select agreements or partner-university pages.
- Reject unrelated international pages.
- Reject staff-only/faculty-only teaching or training mobility pages unless they also include student Erasmus information.
- Reject one-off Erasmus event/news pages, guest lectures, workshops, conferences, or seminars unless they contain durable student Erasmus application, deadline, requirement, partner, agreement, studies, or traineeship information.
- PDF, Word, and spreadsheet URLs may be selected when their filename or link metadata indicates useful Erasmus student information.
- Do not reject a document URL only because the content cannot be parsed in this selection step.

Categories:
agreements, partner_universities, outgoing_studies, deadlines,
application_requirements, learning_agreement, traineeship,
general_erasmus_information, irrelevant

Use relevance_score as an integer from 0 to 100, where 100 means definitely useful.
Return exactly {len(items)} classifications, one for every input URL. Use the exact input URL string.

Input URLs:
{compact_items}
"""


def _normalize_gemini_result(row, metadata: Dict[str, Any], result: Dict[str, Any]) -> UrlClassification:
    if result.get("error"):
        return _rejected_classification(row, str(result.get("message") or result.get("error")), metadata)

    category = str(result.get("category", "irrelevant")).strip()
    if category not in ALLOWED_CATEGORIES:
        category = "irrelevant"

    expected_data = result.get("expected_data", [])
    if not isinstance(expected_data, list):
        expected_data = json_loads_list(str(expected_data))

    relevance_score = max(0, min(100, _safe_int(result.get("relevance_score"), 0)))
    if 1 <= relevance_score <= 10:
        relevance_score *= 10
    selected = bool(result.get("selected", False)) and category != "irrelevant"
    reason = str(result.get("reason", "")).strip()
    reason = f"{reason} [classified_by=gemini]" if reason else "[classified_by=gemini]"

    return UrlClassification(
        university_key=row["university_key"],
        base_url_id=row["base_url_id"] or 0,
        url=row["url"],
        title=str(metadata.get("title") or row["title"] or ""),
        snippet=truncate(str(metadata.get("snippet") or ""), 500),
        selected=selected,
        category=category,
        relevance_score=relevance_score,
        reason=reason,
        expected_data=[str(item) for item in expected_data],
        priority=str(result.get("priority", "low")),
    )


def _classify_gemini_batch(
    items: List[Dict[str, Any]],
    model: str,
    timeout_seconds: int,
) -> List[UrlClassification]:
    if not items:
        return []

    result = call_gemini_json(
        _build_batch_prompt(items),
        schema=url_classification_schema(),
        model=model,
        timeout_seconds=timeout_seconds,
        system_prompt=(
            "You classify Erasmus source URLs for a university information dataset. "
            "Follow the schema exactly and never invent facts."
        ),
    )
    if result.get("error"):
        message = result.get("message") or result.get("error")
        status_code = result.get("status_code") or ""
        raise RuntimeError(f"Gemini URL classification failed ({status_code}): {message}")

    classifications = result.get("classifications", [])
    if not isinstance(classifications, list):
        classifications = []
    by_url = {str(item.get("url") or "").strip(): item for item in classifications if isinstance(item, dict)}

    output: List[UrlClassification] = []
    for item in items:
        row = item["row"]
        metadata = item["metadata"]
        output.append(
            _normalize_gemini_result(
                row,
                metadata,
                by_url.get(row["url"], {"error": "Missing classification for URL in Gemini batch response"}),
            )
        )
    return output


def classify_candidate_urls_with_gemini(
    conn,
    university_key: Optional[str] = None,
    limit: Optional[int] = None,
    content_type: Optional[str] = None,
    batch_size: int = 10,
    model: Optional[str] = None,
    timeout_seconds: int = 120,
    batch_delay_seconds: float = 10.0,
) -> None:
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    if not has_gemini_key():
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env before URL selection.")

    rows = get_candidate_urls(conn, university_key, limit, content_type)
    selected_count = 0
    saved_count = 0
    gemini_items: List[Dict[str, Any]] = []
    batch_size = max(1, batch_size)

    with tqdm(total=len(rows), desc="Classifying URLs with Gemini") as progress:
        for row in rows:
            prepared = _prepare_item(row)
            if isinstance(prepared, UrlClassification):
                upsert_url_classification(conn, prepared)
                saved_count += 1
                progress.update(1)
                continue

            gemini_items.append(prepared)
            if len(gemini_items) < batch_size:
                continue

            for classification in _classify_gemini_batch(gemini_items, model, timeout_seconds):
                upsert_url_classification(conn, classification)
                if classification.selected:
                    selected_count += 1
                saved_count += 1
                progress.update(1)
            gemini_items = []
            if batch_delay_seconds > 0:
                time.sleep(batch_delay_seconds)

        if gemini_items:
            for classification in _classify_gemini_batch(gemini_items, model, timeout_seconds):
                upsert_url_classification(conn, classification)
                if classification.selected:
                    selected_count += 1
                saved_count += 1
                progress.update(1)

    log_event(
        conn,
        "gemini_url_classification",
        "ok",
        f"Classified {saved_count} URLs with Gemini/{model}; selected {selected_count}",
        university_key or "",
    )
