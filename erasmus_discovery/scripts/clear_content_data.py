import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.content_ingestion.cleanup import clear_content_ingestion_state
from src.storage.database import get_connection, initialize_database


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clear scraped documents, chunks, agreements, extraction logs, and Chroma data."
    )
    parser.add_argument("--university-key", default=None, help="Optional university key to clear only one university.")
    parser.add_argument("--keep-chroma", action="store_true", help="Do not clear chroma_db files.")
    args = parser.parse_args()

    initialize_database()
    with get_connection() as conn:
        clear_content_ingestion_state(
            conn,
            university_key=args.university_key,
            clear_chroma=not args.keep_chroma,
        )

    target = args.university_key or "all universities"
    print(f"Cleared content ingestion data for {target}. selected_urls were preserved.")


if __name__ == "__main__":
    main()

