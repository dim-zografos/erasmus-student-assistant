from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_universities
from src.storage.database import get_connection, initialize_database, save_universities
from src.utils import DB_PATH


def main() -> None:
    initialize_database()
    with get_connection() as conn:
        save_universities(conn, load_universities())
    print(f"Initialized database at {DB_PATH}")


if __name__ == "__main__":
    main()
