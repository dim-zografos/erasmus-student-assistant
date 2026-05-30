from typing import Optional

from ..storage.database import get_selected_urls_for_ingestion


def load_selected_sources(
    conn,
    university_key: Optional[str] = None,
    base_url_id: Optional[int] = None,
    include_processed: bool = False,
    limit: Optional[int] = None,
):
    """Return approved selected_urls that should be fetched by content ingestion."""
    return get_selected_urls_for_ingestion(
        conn,
        university_key=university_key,
        base_url_id=base_url_id,
        include_processed=include_processed,
        limit=limit,
    )
