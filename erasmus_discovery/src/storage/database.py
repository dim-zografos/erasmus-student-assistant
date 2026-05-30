import sqlite3
from pathlib import Path
from typing import Any, Iterable, List, Optional

from ..core.models import (
    AgreementCandidate,
    DiscoveredUrl,
    ErasmusAgreement,
    PipelineLog,
    ScrapedDocument,
    UniversityConfig,
    UrlClassification,
)
from ..utils import DB_PATH, ensure_directories, hash_values, json_dumps, now_iso


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_directories()
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: Path = DB_PATH) -> None:
    ensure_directories()
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS universities (
                key TEXT PRIMARY KEY,
                name TEXT,
                country TEXT,
                city TEXT,
                base_erasmus_url TEXT,
                allowed_domains TEXT,
                enabled INTEGER
            );

            CREATE TABLE IF NOT EXISTS base_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                university_key TEXT,
                base_url TEXT,
                allowed_domains TEXT,
                enabled INTEGER,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(university_key, base_url)
            );

            CREATE TABLE IF NOT EXISTS discovered_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                university_key TEXT,
                base_url_id INTEGER,
                url TEXT UNIQUE,
                title TEXT,
                content_type TEXT,
                depth INTEGER,
                discovered_from TEXT,
                matched_keywords TEXT,
                url_score INTEGER,
                status TEXT,
                discovered_at TEXT
            );

            CREATE TABLE IF NOT EXISTS url_classifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                university_key TEXT,
                base_url_id INTEGER,
                url TEXT UNIQUE,
                title TEXT,
                snippet TEXT,
                selected INTEGER,
                category TEXT,
                relevance_score INTEGER,
                reason TEXT,
                expected_data TEXT,
                priority TEXT,
                classified_at TEXT
            );

            CREATE TABLE IF NOT EXISTS selected_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base_url_id INTEGER,
                university_key TEXT,
                url TEXT UNIQUE,
                title TEXT,
                content_type TEXT,
                category TEXT,
                relevance_score INTEGER,
                reason TEXT,
                expected_data TEXT,
                priority TEXT,
                status TEXT,
                selected_at TEXT
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step TEXT,
                university_key TEXT,
                url TEXT,
                status TEXT,
                message TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS scraped_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selected_url_id INTEGER,
                university_key TEXT,
                university_name TEXT,
                source_url TEXT UNIQUE,
                title TEXT,
                category TEXT,
                cleaned_content TEXT,
                document_type TEXT,
                key_topics TEXT,
                contains_agreements INTEGER,
                contains_deadlines INTEGER,
                contains_requirements INTEGER,
                scraped_at TEXT,
                content_hash TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selected_url_id INTEGER,
                document_id INTEGER,
                university_key TEXT,
                university_name TEXT,
                source_url TEXT,
                category TEXT,
                chunk_text TEXT,
                chunk_index INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS erasmus_agreements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                home_university_key TEXT,
                home_university TEXT,
                department TEXT,
                partner_university TEXT,
                partner_country TEXT,
                deadline TEXT,
                academic_year TEXT,
                source_url TEXT,
                evidence_text TEXT,
                confidence TEXT,
                extracted_at TEXT,
                row_hash TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS agreement_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                home_university_key TEXT,
                home_university TEXT,
                department TEXT,
                partner_university TEXT,
                partner_country TEXT,
                deadline TEXT,
                academic_year TEXT,
                source_url TEXT,
                evidence_text TEXT,
                confidence TEXT,
                reason TEXT,
                extracted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS structured_extraction_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                source_url TEXT,
                status TEXT,
                records_found INTEGER,
                message TEXT,
                extracted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS content_ingestion_skips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selected_url_id INTEGER,
                university_key TEXT,
                source_url TEXT UNIQUE,
                reason TEXT,
                skipped_at TEXT
            );
            """
        )
        _ensure_content_columns(conn)
        _backfill_url_layers(conn)


def _base_url_id_for_university(conn: sqlite3.Connection, university_key: str) -> int:
    row = conn.execute(
        "SELECT id FROM base_urls WHERE university_key=? ORDER BY enabled DESC, id LIMIT 1",
        (university_key,),
    ).fetchone()
    return int(row["id"]) if row else 0


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_content_columns(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "scraped_documents", "selected_url_id", "INTEGER")
    _ensure_column(conn, "chunks", "selected_url_id", "INTEGER")


def _base_url_id_for_url(conn: sqlite3.Connection, university_key: str, url: str) -> int:
    row = conn.execute("SELECT base_url_id FROM discovered_urls WHERE url=? LIMIT 1", (url,)).fetchone()
    if row and row["base_url_id"]:
        return int(row["base_url_id"])
    row = conn.execute("SELECT base_url_id FROM url_classifications WHERE url=? LIMIT 1", (url,)).fetchone()
    if row and row["base_url_id"]:
        return int(row["base_url_id"])
    return _base_url_id_for_university(conn, university_key)


def _backfill_url_layers(conn: sqlite3.Connection) -> None:
    now = now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO base_urls (university_key, base_url, allowed_domains, enabled, created_at, updated_at)
        SELECT key, base_erasmus_url, allowed_domains, enabled, ?, ?
        FROM universities
        WHERE COALESCE(base_erasmus_url, '') != ''
        """,
        (now, now),
    )
    conn.execute(
        """
        UPDATE discovered_urls
        SET base_url_id = (
            SELECT id FROM base_urls b
            WHERE b.university_key = discovered_urls.university_key
            ORDER BY b.enabled DESC, b.id
            LIMIT 1
        )
        WHERE COALESCE(base_url_id, 0) = 0
        """
    )
    conn.execute(
        """
        UPDATE url_classifications
        SET base_url_id = (
            SELECT COALESCE(d.base_url_id, b.id)
            FROM base_urls b
            LEFT JOIN discovered_urls d ON d.url = url_classifications.url
            WHERE b.university_key = url_classifications.university_key
            ORDER BY b.enabled DESC, b.id
            LIMIT 1
        )
        WHERE COALESCE(base_url_id, 0) = 0
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO selected_urls (
            id,
            base_url_id, university_key, url, title, content_type, category,
            relevance_score, reason, expected_data, priority, status, selected_at
        )
        SELECT
            (SELECT id FROM selected_urls existing WHERE existing.url = c.url),
            COALESCE(
                NULLIF(c.base_url_id, 0),
                NULLIF(d.base_url_id, 0),
                (
                    SELECT id
                    FROM base_urls
                    WHERE university_key = c.university_key
                    ORDER BY enabled DESC, id
                    LIMIT 1
                ),
                0
            ),
            c.university_key,
            c.url,
            c.title,
            COALESCE(d.content_type, ''),
            c.category,
            c.relevance_score,
            c.reason,
            c.expected_data,
            c.priority,
            'approved',
            c.classified_at
        FROM url_classifications c
        LEFT JOIN discovered_urls d ON d.url = c.url
        WHERE c.selected = 1
        """
    )
    conn.commit()


def save_universities(conn: sqlite3.Connection, universities: Iterable[UniversityConfig]) -> None:
    for university in universities:
        conn.execute(
            """
            INSERT INTO universities (key, name, country, city, base_erasmus_url, allowed_domains, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name=excluded.name,
                country=excluded.country,
                city=excluded.city,
                base_erasmus_url=excluded.base_erasmus_url,
                allowed_domains=excluded.allowed_domains,
                enabled=excluded.enabled
            """,
            (
                university.key,
                university.name,
                university.country,
                university.city,
                university.base_erasmus_url,
                json_dumps(university.allowed_domains),
                1 if university.enabled else 0,
            ),
        )
        now = now_iso()
        conn.execute(
            """
            INSERT INTO base_urls (university_key, base_url, allowed_domains, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(university_key, base_url) DO UPDATE SET
                allowed_domains=excluded.allowed_domains,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """,
            (
                university.key,
                university.base_erasmus_url,
                json_dumps(university.allowed_domains),
                1 if university.enabled else 0,
                now,
                now,
            ),
        )
    conn.commit()
    _backfill_url_layers(conn)


def log_event(
    conn: sqlite3.Connection,
    step: str,
    status: str,
    message: str = "",
    university_key: str = "",
    url: str = "",
) -> None:
    log = PipelineLog(step=step, university_key=university_key, url=url, status=status, message=message, created_at=now_iso())
    conn.execute(
        "INSERT INTO logs (step, university_key, url, status, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (log.step, log.university_key, log.url, log.status, log.message, log.created_at),
    )
    conn.commit()


def insert_discovered_url(conn: sqlite3.Connection, discovered: DiscoveredUrl) -> None:
    discovered.discovered_at = discovered.discovered_at or now_iso()
    base_url_id = discovered.base_url_id or _base_url_id_for_university(conn, discovered.university_key)
    conn.execute(
        """
        INSERT INTO discovered_urls (
            university_key, base_url_id, url, title, content_type, depth, discovered_from,
            matched_keywords, url_score, status, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            base_url_id=COALESCE(NULLIF(excluded.base_url_id, 0), base_url_id),
            title=COALESCE(NULLIF(excluded.title, ''), title),
            content_type=COALESCE(NULLIF(excluded.content_type, ''), content_type),
            depth=MIN(depth, excluded.depth),
            discovered_from=COALESCE(NULLIF(excluded.discovered_from, ''), discovered_from)
        """,
        (
            discovered.university_key,
            base_url_id,
            discovered.url,
            discovered.title,
            discovered.content_type,
            discovered.depth,
            discovered.discovered_from,
            discovered.matched_keywords,
            discovered.url_score,
            discovered.status,
            discovered.discovered_at,
        ),
    )
    conn.commit()


def update_discovered_prefilter(
    conn: sqlite3.Connection,
    url: str,
    matched_keywords: str,
    url_score: int,
    status: str,
) -> None:
    conn.execute(
        "UPDATE discovered_urls SET matched_keywords=?, url_score=?, status=? WHERE url=?",
        (matched_keywords, url_score, status, url),
    )
    conn.commit()


def fetch_rows(conn: sqlite3.Connection, query: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
    return list(conn.execute(query, tuple(params)).fetchall())


def get_discovered_urls(conn: sqlite3.Connection, university_key: Optional[str] = None) -> List[sqlite3.Row]:
    if university_key:
        return fetch_rows(conn, "SELECT * FROM discovered_urls WHERE university_key=? ORDER BY id", (university_key,))
    return fetch_rows(conn, "SELECT * FROM discovered_urls ORDER BY id")


def count_discovered_urls(conn: sqlite3.Connection, university_key: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM discovered_urls WHERE university_key=?",
        (university_key,),
    ).fetchone()
    return int(row["count"] or 0)


def clear_discovery_data(conn: sqlite3.Connection, university_key: Optional[str] = None) -> None:
    if university_key:
        conn.execute("DELETE FROM selected_urls WHERE university_key=?", (university_key,))
        conn.execute("DELETE FROM url_classifications WHERE university_key=?", (university_key,))
        conn.execute("DELETE FROM discovered_urls WHERE university_key=?", (university_key,))
        log_event(conn, "discovery", "reset", "Cleared discovered URLs and dependent URL selections", university_key)
    else:
        conn.execute("DELETE FROM selected_urls")
        conn.execute("DELETE FROM url_classifications")
        conn.execute("DELETE FROM discovered_urls")
        log_event(conn, "discovery", "reset", "Cleared all discovered URLs and dependent URL selections")
    conn.commit()


def get_candidate_urls(
    conn: sqlite3.Connection,
    university_key: Optional[str] = None,
    limit: Optional[int] = None,
    content_type: Optional[str] = None,
) -> List[sqlite3.Row]:
    query = """
        SELECT d.*
        FROM discovered_urls d
        LEFT JOIN url_classifications c ON c.url = d.url
        WHERE d.status='candidate'
          AND (
              c.url IS NULL
              OR c.reason LIKE '%Gemini request failed%'
              OR c.reason LIKE '%Gemini invalid JSON%'
              OR c.reason LIKE '%Missing classification for URL in Gemini batch response%'
              OR c.reason LIKE '%429 Client Error%'
              OR c.reason LIKE '%Too Many Requests%'
          )
    """
    params: List[Any] = []
    if university_key:
        query += " AND d.university_key=?"
        params.append(university_key)
    if content_type:
        query += " AND d.content_type=?"
        params.append(content_type)
    query += " ORDER BY d.url_score DESC, d.id"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return fetch_rows(conn, query, params)


def clear_url_selection(conn: sqlite3.Connection, university_key: Optional[str] = None) -> None:
    if university_key:
        conn.execute("DELETE FROM selected_urls WHERE university_key=?", (university_key,))
        conn.execute("DELETE FROM url_classifications WHERE university_key=?", (university_key,))
        log_event(conn, "url_selection", "reset", "Cleared existing URL classifications", university_key)
    else:
        conn.execute("DELETE FROM selected_urls")
        conn.execute("DELETE FROM url_classifications")
        log_event(conn, "url_selection", "reset", "Cleared all existing URL classifications")
    conn.commit()


def clear_content_data(conn: sqlite3.Connection, university_key: Optional[str] = None) -> None:
    tables = [
        "erasmus_agreements",
        "agreement_candidates",
        "structured_extraction_logs",
        "content_ingestion_skips",
        "chunks",
        "scraped_documents",
    ]
    if university_key:
        document_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM scraped_documents WHERE university_key=?",
                (university_key,),
            ).fetchall()
        ]
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            conn.execute(f"DELETE FROM erasmus_agreements WHERE document_id IN ({placeholders})", document_ids)
            conn.execute(f"DELETE FROM agreement_candidates WHERE document_id IN ({placeholders})", document_ids)
            conn.execute(f"DELETE FROM structured_extraction_logs WHERE document_id IN ({placeholders})", document_ids)
            conn.execute(f"DELETE FROM chunks WHERE document_id IN ({placeholders})", document_ids)
        conn.execute("DELETE FROM scraped_documents WHERE university_key=?", (university_key,))
        conn.execute("DELETE FROM content_ingestion_skips WHERE university_key=?", (university_key,))
        message = f"Cleared content ingestion data for {university_key}"
    else:
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
        message = "Cleared all content ingestion data"
    log_event(conn, "content_ingestion", "reset", message, university_key or "")
    conn.commit()


def get_selected_urls_for_ingestion(
    conn: sqlite3.Connection,
    university_key: Optional[str] = None,
    base_url_id: Optional[int] = None,
    include_processed: bool = False,
    limit: Optional[int] = None,
) -> List[sqlite3.Row]:
    query = """
        SELECT
            s.*,
            u.name AS university_name,
            u.allowed_domains AS university_allowed_domains
        FROM selected_urls s
        JOIN universities u ON u.key = s.university_key
        LEFT JOIN scraped_documents d ON d.selected_url_id = s.id OR d.source_url = s.url
        LEFT JOIN content_ingestion_skips k ON k.selected_url_id = s.id OR k.source_url = s.url
        WHERE s.status='approved'
    """
    params: List[Any] = []
    if not include_processed:
        query += " AND d.id IS NULL AND k.id IS NULL"
    if university_key:
        query += " AND s.university_key=?"
        params.append(university_key)
    if base_url_id:
        query += " AND s.base_url_id=?"
        params.append(base_url_id)
    query += " ORDER BY s.base_url_id, s.university_key, s.relevance_score DESC, s.id"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return fetch_rows(conn, query, params)


def save_content_ingestion_skip(
    conn: sqlite3.Connection,
    selected_url_id: int,
    university_key: str,
    source_url: str,
    reason: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM scraped_documents WHERE selected_url_id=? OR source_url=?",
        (selected_url_id, source_url),
    ).fetchone()
    if existing:
        _delete_document_children(conn, int(existing["id"]))
        conn.execute("DELETE FROM scraped_documents WHERE id=?", (int(existing["id"]),))
    conn.execute(
        """
        INSERT INTO content_ingestion_skips (
            selected_url_id, university_key, source_url, reason, skipped_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_url) DO UPDATE SET
            selected_url_id=excluded.selected_url_id,
            university_key=excluded.university_key,
            reason=excluded.reason,
            skipped_at=excluded.skipped_at
        """,
        (selected_url_id, university_key, source_url, reason, now_iso()),
    )
    conn.commit()


def save_scraped_document(conn: sqlite3.Connection, document: ScrapedDocument) -> int:
    document.scraped_at = document.scraped_at or now_iso()
    document.content_hash = document.content_hash or hash_values([document.source_url, document.cleaned_content])

    conn.execute(
        "DELETE FROM content_ingestion_skips WHERE selected_url_id=? OR source_url=?",
        (document.selected_url_id, document.source_url),
    )
    existing = conn.execute(
        "SELECT id FROM scraped_documents WHERE source_url=?",
        (document.source_url,),
    ).fetchone()
    if existing:
        _delete_document_children(conn, int(existing["id"]))

    conn.execute(
        """
        INSERT INTO scraped_documents (
            selected_url_id, university_key, university_name, source_url, title,
            category, cleaned_content, document_type, key_topics,
            contains_agreements, contains_deadlines, contains_requirements,
            scraped_at, content_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_url) DO UPDATE SET
            selected_url_id=excluded.selected_url_id,
            university_key=excluded.university_key,
            university_name=excluded.university_name,
            title=excluded.title,
            category=excluded.category,
            cleaned_content=excluded.cleaned_content,
            document_type=excluded.document_type,
            key_topics=excluded.key_topics,
            contains_agreements=excluded.contains_agreements,
            contains_deadlines=excluded.contains_deadlines,
            contains_requirements=excluded.contains_requirements,
            scraped_at=excluded.scraped_at,
            content_hash=excluded.content_hash
        """,
        (
            document.selected_url_id,
            document.university_key,
            document.university_name,
            document.source_url,
            document.title,
            document.category,
            document.cleaned_content,
            document.document_type,
            json_dumps(document.key_topics),
            1 if document.contains_agreements else 0,
            1 if document.contains_deadlines else 0,
            1 if document.contains_requirements else 0,
            document.scraped_at,
            document.content_hash,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM scraped_documents WHERE source_url=?", (document.source_url,)).fetchone()
    return int(row["id"])


def replace_document_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    selected_url_id: int,
    university_key: str,
    university_name: str,
    source_url: str,
    category: str,
    chunks: List[str],
) -> None:
    conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    created_at = now_iso()
    for index, chunk_text in enumerate(chunks):
        conn.execute(
            """
            INSERT INTO chunks (
                selected_url_id, document_id, university_key, university_name,
                source_url, category, chunk_text, chunk_index, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selected_url_id,
                document_id,
                university_key,
                university_name,
                source_url,
                category,
                chunk_text,
                index,
                created_at,
            ),
        )
    conn.commit()


def save_erasmus_agreement(conn: sqlite3.Connection, agreement: ErasmusAgreement) -> bool:
    if not agreement.partner_university.strip():
        return False
    agreement.extracted_at = agreement.extracted_at or now_iso()
    agreement.row_hash = agreement.row_hash or hash_values(
        [
            agreement.source_url,
            agreement.home_university_key,
            agreement.department,
            agreement.partner_university,
            agreement.partner_country,
            agreement.academic_year,
        ]
    )
    existing = conn.execute(
        "SELECT id FROM erasmus_agreements WHERE row_hash=?",
        (agreement.row_hash,),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO erasmus_agreements (
            document_id, home_university_key, home_university, department,
            partner_university, partner_country, deadline, academic_year,
            source_url, evidence_text, confidence, extracted_at, row_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(row_hash) DO UPDATE SET
              evidence_text=excluded.evidence_text,
              confidence=excluded.confidence,
              extracted_at=excluded.extracted_at
        """,
        (
            agreement.document_id,
            agreement.home_university_key,
            agreement.home_university,
            agreement.department,
            agreement.partner_university,
            agreement.partner_country,
            agreement.deadline,
            agreement.academic_year,
            agreement.source_url,
            agreement.evidence_text,
            agreement.confidence,
            agreement.extracted_at,
            agreement.row_hash,
        ),
    )
    conn.commit()
    return existing is None


def save_agreement_candidate(conn: sqlite3.Connection, candidate: AgreementCandidate) -> None:
    candidate.extracted_at = candidate.extracted_at or now_iso()
    conn.execute(
        """
        INSERT INTO agreement_candidates (
            document_id, home_university_key, home_university, department,
            partner_university, partner_country, deadline, academic_year,
            source_url, evidence_text, confidence, reason, extracted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate.document_id,
            candidate.home_university_key,
            candidate.home_university,
            candidate.department,
            candidate.partner_university,
            candidate.partner_country,
            candidate.deadline,
            candidate.academic_year,
            candidate.source_url,
            candidate.evidence_text,
            candidate.confidence,
            candidate.reason,
            candidate.extracted_at,
        ),
    )
    conn.commit()


def save_structured_extraction_log(
    conn: sqlite3.Connection,
    document_id: int,
    source_url: str,
    status: str,
    records_found: int,
    message: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO structured_extraction_logs (
            document_id, source_url, status, records_found, message, extracted_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (document_id, source_url, status, records_found, message, now_iso()),
    )
    conn.commit()


def _delete_document_children(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM erasmus_agreements WHERE document_id=?", (document_id,))
    conn.execute("DELETE FROM agreement_candidates WHERE document_id=?", (document_id,))
    conn.execute("DELETE FROM structured_extraction_logs WHERE document_id=?", (document_id,))
    conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))


def upsert_url_classification(conn: sqlite3.Connection, classification: UrlClassification) -> None:
    classification.classified_at = classification.classified_at or now_iso()
    base_url_id = classification.base_url_id or _base_url_id_for_url(
        conn,
        classification.university_key,
        classification.url,
    )
    conn.execute(
        """
        INSERT INTO url_classifications (
            university_key, base_url_id, url, title, snippet, selected, category,
            relevance_score, reason, expected_data, priority, classified_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            university_key=excluded.university_key,
            base_url_id=excluded.base_url_id,
            title=excluded.title,
            snippet=excluded.snippet,
            selected=excluded.selected,
            category=excluded.category,
            relevance_score=excluded.relevance_score,
            reason=excluded.reason,
            expected_data=excluded.expected_data,
            priority=excluded.priority,
            classified_at=excluded.classified_at
        """,
        (
            classification.university_key,
            base_url_id,
            classification.url,
            classification.title,
            classification.snippet,
            1 if classification.selected else 0,
            classification.category,
            classification.relevance_score,
            classification.reason,
            json_dumps(classification.expected_data),
            classification.priority,
            classification.classified_at,
        ),
    )
    conn.commit()
    _sync_selected_url_for_classification(conn, classification, base_url_id)


def _sync_selected_url_for_classification(
    conn: sqlite3.Connection,
    classification: UrlClassification,
    base_url_id: int,
) -> None:
    if not classification.selected:
        conn.execute(
            """
            UPDATE selected_urls
            SET status='rejected',
                reason=CASE
                    WHEN reason IS NULL OR reason='' THEN ?
                    ELSE reason || ' | ' || ?
                END
            WHERE url=?
            """,
            (classification.reason, classification.reason, classification.url),
        )
        conn.commit()
        return

    content_type_row = conn.execute(
        "SELECT content_type FROM discovered_urls WHERE url=? LIMIT 1",
        (classification.url,),
    ).fetchone()
    content_type = content_type_row["content_type"] if content_type_row else ""
    conn.execute(
        """
        INSERT INTO selected_urls (
            base_url_id, university_key, url, title, content_type, category,
            relevance_score, reason, expected_data, priority, status, selected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?)
        ON CONFLICT(url) DO UPDATE SET
            base_url_id=excluded.base_url_id,
            university_key=excluded.university_key,
            title=excluded.title,
            content_type=excluded.content_type,
            category=excluded.category,
            relevance_score=excluded.relevance_score,
            reason=excluded.reason,
            expected_data=excluded.expected_data,
            priority=excluded.priority,
            status='approved',
            selected_at=excluded.selected_at
        """,
        (
            base_url_id,
            classification.university_key,
            classification.url,
            classification.title,
            content_type,
            classification.category,
            classification.relevance_score,
            classification.reason,
            json_dumps(classification.expected_data),
            classification.priority,
            classification.classified_at,
        ),
    )
    conn.commit()
