from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

from .fetcher import FetchedSource
from .spreadsheet_agreements import extract_legacy_xls_agreements


@dataclass
class StructuredSourceDocument:
    title: str
    category: str
    cleaned_content: str
    document_type: str
    key_topics: list[str] = field(default_factory=list)
    contains_agreements: bool = False
    contains_deadlines: bool = False
    contains_requirements: bool = False
    agreements: list[Dict[str, Any]] = field(default_factory=list)
    dedupe_scope: str = "source"


def parse_structured_source(
    row,
    fetched: FetchedSource,
    agreement_categories: Iterable[str],
) -> Optional[StructuredSourceDocument]:
    """Parse sources where structured records can be read without an LLM."""
    category = row["category"] or ""
    if fetched.content_type == "xls" and category in set(agreement_categories):
        return _parse_legacy_xls_agreements(row, fetched)
    return None


def _parse_legacy_xls_agreements(row, fetched: FetchedSource) -> Optional[StructuredSourceDocument]:
    result = extract_legacy_xls_agreements(fetched.data, fetched.title or row["title"] or row["url"])
    if not result:
        return None
    return StructuredSourceDocument(
        title=row["title"] or "Erasmus+ bilateral agreements spreadsheet",
        category=row["category"] or "agreements",
        cleaned_content=result.cleaned_content,
        document_type="erasmus_partner_agreements_spreadsheet",
        key_topics=["bilateral agreements", "partner universities", "student mobility"],
        contains_agreements=True,
        agreements=result.agreements,
        # AUA publishes repeated historical XLS files. This scope is explicit and
        # limited to structured spreadsheets, not a global database behavior.
        dedupe_scope="university",
    )
