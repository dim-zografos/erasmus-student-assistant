import hashlib
import math
import re

import chromadb

from ..utils import PROJECT_ROOT


CHROMA_PATH = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "erasmus_chunks"
EMBEDDING_DIMENSIONS = 64


def rebuild_vector_store(conn, chroma_path=CHROMA_PATH) -> int:
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.get_or_create_collection(COLLECTION_NAME)

    rows = conn.execute(
        """
        SELECT
            c.id, c.document_id, c.university_key, c.university_name, c.source_url,
            c.category, c.chunk_text, c.chunk_index, d.title
        FROM chunks c
        JOIN scraped_documents d ON d.id = c.document_id
        ORDER BY c.id
        """
    ).fetchall()

    batch_size = 200
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        collection.add(
            ids=[f"chunk-{row['id']}" for row in batch],
            documents=[row["chunk_text"] for row in batch],
            embeddings=[hash_embedding(row["chunk_text"]) for row in batch],
            metadatas=[
                {
                    "document_id": row["document_id"],
                    "university_key": row["university_key"],
                    "university_name": row["university_name"],
                    "source_url": row["source_url"],
                    "category": row["category"],
                    "title": row["title"] or "",
                    "chunk_index": row["chunk_index"],
                }
                for row in batch
            ],
        )
    return len(rows)


def hash_embedding(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = re.findall(r"[A-Za-zΑ-Ωα-ω0-9]+", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        bucket = int.from_bytes(digest, "big") % dimensions
        vector[bucket] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]
