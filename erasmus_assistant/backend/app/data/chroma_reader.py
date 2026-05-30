from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

import chromadb


COLLECTION_NAME = "erasmus_chunks"
EMBEDDING_DIMENSIONS = 64


class ChromaReader:
    """Read retrieval chunks from the Chroma collection built by erasmus_discovery."""

    def __init__(self, chroma_path: Path):
        self.chroma_path = Path(chroma_path).resolve()
        self._collection = None

    def collection(self):
        if self._collection is None:
            client = chromadb.PersistentClient(path=str(self.chroma_path))
            self._collection = client.get_collection(COLLECTION_NAME)
        return self._collection

    def search(self, question: str, university_keys: Iterable[str] = (), limit: int = 8) -> List[Dict[str, Any]]:
        where = None
        keys = [key for key in university_keys if key]
        if len(keys) == 1:
            where = {"university_key": keys[0]}

        result = self.collection().query(
            query_embeddings=[hash_embedding(question)],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        rows: List[Dict[str, Any]] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for idx, chunk_id in enumerate(ids):
            meta = metas[idx] or {}
            rows.append(
                {
                    "chunk_id": _chunk_number(chunk_id),
                    "document_id": meta.get("document_id"),
                    "university_key": meta.get("university_key", ""),
                    "university_name": meta.get("university_name", ""),
                    "source_url": meta.get("source_url", ""),
                    "category": meta.get("category", ""),
                    "title": meta.get("title", ""),
                    "chunk_index": meta.get("chunk_index"),
                    "chunk_text": docs[idx] or "",
                    "distance": distances[idx] if idx < len(distances) else None,
                }
            )
        return rows


def hash_embedding(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> List[float]:
    vector = [0.0] * dimensions
    tokens = re.findall(r"[A-Za-zΞ‘-Ξ©Ξ±-Ο‰0-9]+", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        bucket = int.from_bytes(digest, "big") % dimensions
        vector[bucket] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _chunk_number(value: Any) -> int | None:
    text = str(value or "")
    if text.startswith("chunk-"):
        text = text[6:]
    try:
        return int(text)
    except ValueError:
        return None
