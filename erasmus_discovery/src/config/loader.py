import json
from pathlib import Path
from typing import List

from ..core.models import UniversityConfig
from ..utils import CONFIG_PATH


def load_universities(config_path: Path = CONFIG_PATH, enabled_only: bool = True) -> List[UniversityConfig]:
    with open(config_path, "r", encoding="utf-8") as file:
        raw_items = json.load(file)

    universities: List[UniversityConfig] = []
    for item in raw_items:
        university = UniversityConfig(
            key=str(item.get("key", "")).strip(),
            name=str(item.get("name", "")).strip(),
            country=str(item.get("country", "")).strip(),
            city=str(item.get("city", "")).strip(),
            base_erasmus_url=str(item.get("base_erasmus_url", "")).strip().rstrip("/"),
            allowed_domains=list(item.get("allowed_domains", [])),
            enabled=bool(item.get("enabled", True)),
        )
        if not university.key or not university.base_erasmus_url or not university.allowed_domains:
            continue
        if enabled_only and not university.enabled:
            continue
        universities.append(university)
    return universities
