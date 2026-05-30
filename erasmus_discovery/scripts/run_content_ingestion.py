import argparse
from pathlib import Path
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.content_ingestion.cleanup import clear_content_ingestion_state
from src.content_ingestion.pipeline import ingest_selected_sources
from src.storage.database import get_connection, initialize_database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch selected URLs one at a time, clean content in English, extract agreements, and chunk documents."
    )
    parser.add_argument("--university-key", default=None)
    parser.add_argument("--base-url-id", type=int, default=None, help="Run ingestion for one configured base URL.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--include-processed", action="store_true", help="Reprocess URLs that already have documents.")
    parser.add_argument("--reset-content", action="store_true", help="Clear downstream content data before running.")
    parser.add_argument("--skip-vector-rebuild", action="store_true", help="Do not rebuild ChromaDB after ingestion.")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between selected URLs.")
    args = parser.parse_args()

    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    initialize_database()
    with get_connection() as conn:
        if args.reset_content:
            clear_content_ingestion_state(conn, university_key=args.university_key, clear_chroma=True)
        stats = ingest_selected_sources(
            conn,
            university_key=args.university_key,
            base_url_id=args.base_url_id,
            limit=args.limit,
            include_processed=args.include_processed,
            model=args.model,
            rebuild_vectors=not args.skip_vector_rebuild,
            delay_seconds=args.delay,
        )
    print(f"Content ingestion completed: {stats}")


if __name__ == "__main__":
    main()
