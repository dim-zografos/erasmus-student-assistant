from pathlib import Path
import shutil

from ..storage.database import clear_content_data
from ..utils import PROJECT_ROOT


CHROMA_PATH = PROJECT_ROOT / "chroma_db"


def clear_content_ingestion_state(conn, university_key: str | None = None, clear_chroma: bool = True) -> None:
    """Clear derived content data while preserving discovery and selected URLs."""
    clear_content_data(conn, university_key=university_key)
    if clear_chroma:
        clear_chroma_store()


def clear_chroma_store(chroma_path: Path = CHROMA_PATH) -> None:
    chroma_path.mkdir(parents=True, exist_ok=True)
    project_root = PROJECT_ROOT.resolve()
    target = chroma_path.resolve()
    if project_root not in target.parents and target != project_root:
        raise ValueError(f"Refusing to clear Chroma path outside project: {target}")
    for item in target.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

