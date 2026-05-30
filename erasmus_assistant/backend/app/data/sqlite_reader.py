from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class ErasmusSQLiteReader:
    """Small read-only data access layer for the discovery SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()

    def connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        conn = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def counts(self) -> Dict[str, int]:
        tables = [
            "universities",
            "base_urls",
            "selected_urls",
            "scraped_documents",
            "chunks",
            "erasmus_agreements",
            "agreement_candidates",
            "content_ingestion_skips",
        ]
        with self.connect() as conn:
            return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}

    def universities(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT key, name, country, city, base_erasmus_url
                FROM universities
                ORDER BY name
                """
            ).fetchall()
        return [_dict(row) for row in rows]

    def distinct_partner_countries(self) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT partner_country
                FROM erasmus_agreements
                WHERE TRIM(COALESCE(partner_country, '')) <> ''
                ORDER BY partner_country
                """
            ).fetchall()
        return [str(row["partner_country"]) for row in rows]

    def search_agreements(
        self,
        question: str,
        university_keys: Iterable[str] = (),
        partner_country: str = "",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        where = ["1=1"]
        params: List[Any] = []

        keys = [key for key in university_keys if key]
        if keys:
            placeholders = ",".join("?" for _ in keys)
            where.append(f"home_university_key IN ({placeholders})")
            params.extend(keys)

        if partner_country:
            where.append("LOWER(partner_country) = LOWER(?)")
            params.append(partner_country)

        terms = _important_terms(question)
        rows_limit = max(limit * 8, 80)
        sql = f"""
            SELECT
                id, document_id, home_university_key, home_university, department,
                partner_university, partner_country, deadline, academic_year,
                source_url, evidence_text, confidence
            FROM erasmus_agreements
            WHERE {' AND '.join(where)}
            ORDER BY home_university, partner_country, partner_university
            LIMIT ?
        """
        params.append(rows_limit)

        with self.connect() as conn:
            rows = [_dict(row) for row in conn.execute(sql, params).fetchall()]

        scored = sorted(rows, key=lambda row: _agreement_score(row, terms), reverse=True)
        return _dedupe_agreement_rows(scored)[:limit]

    def keyword_chunks(
        self,
        question: str,
        university_keys: Iterable[str] = (),
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        terms = _important_terms(question)
        if not terms:
            return []

        keys = [key for key in university_keys if key]
        where = []
        params: List[Any] = []
        if keys:
            placeholders = ",".join("?" for _ in keys)
            where.append(f"c.university_key IN ({placeholders})")
            params.extend(keys)

        like_terms = terms[:6]
        if like_terms:
            where.append("(" + " OR ".join("LOWER(c.chunk_text) LIKE ?" for _ in like_terms) + ")")
            params.extend([f"%{term}%" for term in like_terms])

        where_sql = "WHERE " + " AND ".join(where) if where else ""
        sql = f"""
            SELECT
                c.id AS chunk_id, c.document_id, c.university_key, c.university_name,
                c.source_url, c.category, c.chunk_text, c.chunk_index, d.title
            FROM chunks c
            JOIN scraped_documents d ON d.id = c.document_id
            {where_sql}
            LIMIT 200
        """
        with self.connect() as conn:
            rows = [_dict(row) for row in conn.execute(sql, params).fetchall()]

        scored = sorted(rows, key=lambda row: _chunk_score(row, terms), reverse=True)
        return scored[:limit]


def _dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _important_terms(text: str) -> List[str]:
    stopwords = {
        "about", "after", "also", "and", "are", "can", "could", "does", "erasmus",
        "for", "from", "have", "how", "into", "is", "me", "of", "on", "or", "plus",
        "should", "student", "students", "that", "the", "their", "there", "this",
        "to", "university", "what", "when", "where", "which", "with",
    }
    terms = []
    for term in re.findall(r"[a-zA-Z][a-zA-Z0-9+-]{2,}", text.lower()):
        if term not in stopwords and term not in terms:
            terms.append(term)
    return terms


def _agreement_score(row: Dict[str, Any], terms: List[str]) -> int:
    haystack = " ".join(str(row.get(key, "")) for key in row.keys()).lower()
    score = sum(3 for term in terms if term in haystack)
    if row.get("confidence") == "high":
        score += 2
    if row.get("evidence_text"):
        score += 1
    return score


def _dedupe_agreement_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (
            str(row.get("home_university_key", "")).lower(),
            str(row.get("department", "")).lower(),
            str(row.get("partner_university", "")).lower(),
            str(row.get("partner_country", "")).lower(),
            str(row.get("academic_year", "")).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _chunk_score(row: Dict[str, Any], terms: List[str]) -> int:
    text = f"{row.get('title', '')} {row.get('category', '')} {row.get('chunk_text', '')}".lower()
    return sum(text.count(term) for term in terms)
