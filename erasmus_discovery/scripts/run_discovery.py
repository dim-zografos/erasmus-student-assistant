from pathlib import Path
import sys
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.database import get_connection, initialize_database
from src.pipeline import load_and_save_universities, run_discovery


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover URLs from configured Erasmus base URLs.")
    parser.add_argument("--university-key", default=None, help="Run discovery for one university key only.")
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Delete discovered URLs and dependent URL selections before scanning.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip universities that already have more than one discovered URL.",
    )
    parser.add_argument(
        "--prefilter-only",
        action="store_true",
        help="Do not fetch websites; only recompute candidate/ignored status for existing discovered URLs.",
    )
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--max-sitemaps", type=int, default=20)
    parser.add_argument("--sitemap-fallback-threshold", type=int, default=5)
    args = parser.parse_args()

    initialize_database()
    with get_connection() as conn:
        universities = load_and_save_universities(conn)
        run_discovery(
            conn,
            universities,
            university_key=args.university_key,
            reset_existing=args.reset_existing,
            skip_existing=args.skip_existing,
            prefilter_only=args.prefilter_only,
            max_depth=args.max_depth,
            max_pages_per_university=args.max_pages,
            delay_seconds=args.delay,
            max_sitemaps=args.max_sitemaps,
            sitemap_fallback_threshold=args.sitemap_fallback_threshold,
        )
    print("Discovery and URL prefilter completed.")


if __name__ == "__main__":
    main()
