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

from src.storage.database import get_connection, initialize_database
from src.pipeline import load_and_save_universities, run_url_selection


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify candidate URLs from discovered_urls and store approved source URLs."
    )
    parser.add_argument("--university-key", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit URL classification, useful while testing.")
    parser.add_argument("--content-type", choices=["html", "pdf", "doc", "docx", "xls", "xlsx"], default=None)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--batch-delay", type=float, default=10.0, help="Seconds to wait between Gemini batches.")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Delete existing URL classifications before running Gemini selection.",
    )
    args = parser.parse_args()

    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    initialize_database()
    with get_connection() as conn:
        load_and_save_universities(conn)
        run_url_selection(
            conn,
            university_key=args.university_key,
            classification_limit=args.limit,
            content_type=args.content_type,
            batch_size=args.batch_size,
            batch_delay_seconds=args.batch_delay,
            model=args.model,
            reset_existing=args.reset_existing,
        )
    print("URL selection completed. Approved URLs are stored in selected_urls.")


if __name__ == "__main__":
    main()
