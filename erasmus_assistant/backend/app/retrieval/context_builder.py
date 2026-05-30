from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ..data.chroma_reader import ChromaReader
from ..data.sqlite_reader import ErasmusSQLiteReader
from .intent import Intent, detect_intent
from .sql_search import search_structured_data
from .vector_search import search_knowledge


@dataclass
class ContextPackage:
    question: str
    intent: Intent
    agreements: List[Dict[str, Any]]
    chunks: List[Dict[str, Any]]
    notes: List[str]


def build_context(
    reader: ErasmusSQLiteReader,
    chroma: ChromaReader,
    question: str,
    max_sources: int = 8,
) -> ContextPackage:
    universities = reader.universities()
    countries = reader.distinct_partner_countries()
    intent = detect_intent(question, universities, countries)

    agreements = search_structured_data(reader, question, intent, limit=25)
    chunk_limit = max_sources
    if intent.name == "agreements" and agreements:
        chunk_limit = max(4, max_sources // 2)
    chunks = search_knowledge(chroma, reader, question, intent, limit=chunk_limit)

    notes: List[str] = []
    if intent.name == "agreements" and not agreements:
        notes.append("No matching confirmed Erasmus agreement rows were found in the stored structured data.")
    if not chunks:
        notes.append("No matching knowledge chunks were found in the stored document chunks.")

    return ContextPackage(
        question=question,
        intent=intent,
        agreements=agreements,
        chunks=chunks[:max_sources],
        notes=notes,
    )
