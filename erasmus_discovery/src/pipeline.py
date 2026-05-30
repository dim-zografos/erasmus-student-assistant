from typing import List, Optional

from .config.loader import load_universities
from .core.models import UniversityConfig
from .discovery.fallback_crawler import crawl_university
from .discovery.sitemap_scanner import scan_sitemaps
from .discovery.url_prefilter import prefilter_urls
from .selection.page_classifier import classify_candidate_urls_with_gemini
from .services.gemini_client import has_gemini_key
from .storage.database import (
    clear_discovery_data,
    clear_url_selection,
    count_discovered_urls,
    get_connection,
    initialize_database,
    log_event,
    save_universities,
)


def load_and_save_universities(conn) -> List[UniversityConfig]:
    universities = load_universities()
    save_universities(conn, universities)
    return universities


def run_discovery(
    conn,
    universities: Optional[List[UniversityConfig]] = None,
    university_key: Optional[str] = None,
    reset_existing: bool = False,
    skip_existing: bool = False,
    prefilter_only: bool = False,
    max_depth: int = 2,
    max_pages_per_university: int = 100,
    delay_seconds: float = 0.4,
    max_sitemaps: int = 20,
    sitemap_fallback_threshold: int = 5,
) -> None:
    universities = universities or load_and_save_universities(conn)
    if university_key:
        universities = [university for university in universities if university.key == university_key]

    if reset_existing:
        clear_discovery_data(conn, university_key)

    total = len(universities)
    for index, university in enumerate(universities, start=1):
        existing_count = count_discovered_urls(conn, university.key)
        if skip_existing and existing_count > 1:
            print(f"[{index}/{total}] {university.key}: skipping existing discovery ({existing_count} URLs)")
            prefilter_urls(conn, university.key)
            continue

        print(f"[{index}/{total}] {university.key}: discovery started")
        if not prefilter_only:
            sitemap_count = scan_sitemaps(conn, university, max_sitemaps=max_sitemaps)
            if sitemap_count < sitemap_fallback_threshold:
                crawl_university(
                    conn,
                    university,
                    max_depth=max_depth,
                    max_pages_per_university=max_pages_per_university,
                    delay_seconds=delay_seconds,
                )
        prefilter_urls(conn, university.key)
        final_count = count_discovered_urls(conn, university.key)
        print(f"[{index}/{total}] {university.key}: discovery stored {final_count} URLs")


def run_url_selection(
    conn,
    university_key: Optional[str] = None,
    classification_limit: Optional[int] = None,
    content_type: Optional[str] = None,
    batch_size: int = 10,
    model: Optional[str] = None,
    batch_delay_seconds: float = 10.0,
    reset_existing: bool = False,
) -> None:
    if reset_existing and not has_gemini_key():
        raise RuntimeError("GEMINI_API_KEY is not set. Existing URL classifications were not changed.")
    if reset_existing:
        clear_url_selection(conn, university_key)
    classify_candidate_urls_with_gemini(
        conn,
        university_key=university_key,
        limit=classification_limit,
        content_type=content_type,
        batch_size=batch_size,
        model=model,
        batch_delay_seconds=batch_delay_seconds,
    )


def run_full_pipeline(
    classification_limit: Optional[int] = None,
    model: Optional[str] = None,
    reset_existing: bool = False,
    max_depth: int = 2,
    max_pages_per_university: int = 100,
    delay_seconds: float = 0.4,
) -> None:
    initialize_database()
    with get_connection() as conn:
        universities = load_and_save_universities(conn)
        log_event(conn, "pipeline", "start", "Starting Erasmus URL selection pipeline")
        run_discovery(
            conn,
            universities,
            max_depth=max_depth,
            max_pages_per_university=max_pages_per_university,
            delay_seconds=delay_seconds,
        )
        run_url_selection(
            conn,
            classification_limit=classification_limit,
            model=model,
            reset_existing=reset_existing,
        )
        log_event(conn, "pipeline", "ok", "Erasmus URL selection pipeline completed")
