from __future__ import annotations

from typing import Any, Dict, List

from ..data.chroma_reader import ChromaReader
from ..data.sqlite_reader import ErasmusSQLiteReader
from .intent import Intent


def search_knowledge(
    chroma: ChromaReader,
    reader: ErasmusSQLiteReader,
    question: str,
    intent: Intent,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    try:
        rows = chroma.search(question, university_keys=intent.university_keys, limit=limit)
        if rows:
            return rows
    except Exception:
        pass
    return reader.keyword_chunks(question, university_keys=intent.university_keys, limit=limit)
