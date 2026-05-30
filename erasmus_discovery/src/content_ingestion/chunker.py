from ..utils import compact_whitespace


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    text = compact_whitespace(text)
    if not text:
        return []
    chunk_size = max(200, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 1))

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks

