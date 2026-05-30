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

from src.pipeline import run_full_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run discovery, prefiltering, and Gemini URL selection.")
    parser.add_argument("--classification-limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Delete existing URL classifications before running Gemini selection.",
    )
    args = parser.parse_args()
    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")
    run_full_pipeline(
        classification_limit=args.classification_limit,
        model=args.model,
        reset_existing=args.reset_existing,
        max_depth=args.max_depth,
        max_pages_per_university=args.max_pages,
        delay_seconds=args.delay,
    )
    print("Full pipeline completed.")


if __name__ == "__main__":
    main()
