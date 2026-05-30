from __future__ import annotations

from typing import Any, Dict, List


def source_items(chunks: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    seen = set()
    sources: List[Dict[str, Any]] = []
    for chunk in chunks:
        key = (chunk.get("source_url"), chunk.get("document_id"))
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "source_url": chunk.get("source_url", ""),
                "title": chunk.get("title", ""),
                "university_key": chunk.get("university_key", ""),
                "university_name": chunk.get("university_name", ""),
                "category": chunk.get("category", ""),
                "document_id": chunk.get("document_id"),
                "chunk_id": chunk.get("chunk_id"),
                "snippet": _snippet(chunk.get("chunk_text", "")),
            }
        )
        if len(sources) >= limit:
            break
    return sources


def _snippet(text: str, limit: int = 320) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
