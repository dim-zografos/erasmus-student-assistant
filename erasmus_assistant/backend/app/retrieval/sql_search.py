from __future__ import annotations

from typing import Any, Dict, List

from ..data.sqlite_reader import ErasmusSQLiteReader
from .intent import Intent


def search_structured_data(
    reader: ErasmusSQLiteReader,
    question: str,
    intent: Intent,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    if intent.name != "agreements" and not intent.partner_country:
        return []
    return reader.search_agreements(
        question=question,
        university_keys=intent.university_keys,
        partner_country=intent.partner_country,
        limit=limit,
    )
