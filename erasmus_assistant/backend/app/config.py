from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv


ASSISTANT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ASSISTANT_ROOT.parent
DISCOVERY_ROOT = WORKSPACE_ROOT / "erasmus_discovery"
FRONTEND_ROOT = ASSISTANT_ROOT / "frontend"

DISCOVERY_ENV = DISCOVERY_ROOT / ".env"
ASSISTANT_ENV = ASSISTANT_ROOT / ".env"

# Load discovery settings first so the assistant .env can override them.
load_dotenv(DISCOVERY_ENV, override=False)
load_dotenv(ASSISTANT_ENV, override=True)


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        return default.resolve()
    path = Path(value)
    if not path.is_absolute():
        path = (ASSISTANT_ROOT / path).resolve()
    return path


ERASMUS_DB_PATH = _path_from_env("ERASMUS_DB_PATH", DISCOVERY_ROOT / "data" / "erasmus.db")
ERASMUS_CHROMA_PATH = _path_from_env("ERASMUS_CHROMA_PATH", DISCOVERY_ROOT / "chroma_db")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def get_gemini_keys() -> List[str]:
    keys: List[str] = []
    combined = os.getenv("GEMINI_API_KEYS", "").strip()
    if combined:
        keys.extend([item.strip() for item in combined.split(",") if item.strip()])

    primary = os.getenv("GEMINI_API_KEY", "").strip()
    if primary:
        keys.append(primary)

    for index in range(1, 10):
        key = os.getenv(f"GEMINI_API_KEY_{index}", "").strip()
        if key:
            keys.append(key)

    deduped: List[str] = []
    seen = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped
