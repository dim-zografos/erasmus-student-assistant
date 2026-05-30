from __future__ import annotations

import traceback
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG_DIR = ROOT / "run_logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "assistant_server.wrapper.log"


def log(message: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


if __name__ == "__main__":
    try:
        log("Starting Erasmus Assistant on http://127.0.0.1:8000")
        uvicorn.run(
            "backend.app.main:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_level="info",
        )
    except Exception:
        log(traceback.format_exc())
        raise
