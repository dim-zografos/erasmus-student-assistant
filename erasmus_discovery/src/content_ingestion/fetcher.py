from dataclasses import dataclass
from typing import Iterable

from ..utils import content_type_from_url, get_url, is_allowed_url


@dataclass
class FetchedSource:
    url: str
    content_type: str
    title: str
    data: bytes
    response_content_type: str = ""


def fetch_selected_source(row, allowed_domains: Iterable[str]) -> FetchedSource:
    url = row["url"]
    if not is_allowed_url(url, allowed_domains):
        raise ValueError(f"URL is outside allowed domains: {url}")

    response = get_url(url, timeout=30)
    response.raise_for_status()
    content_type = _content_type_from_row_or_response(row, response.headers.get("Content-Type", ""))
    return FetchedSource(
        url=url,
        content_type=content_type,
        title=row["title"] or "",
        data=response.content,
        response_content_type=response.headers.get("Content-Type", ""),
    )


def _content_type_from_row_or_response(row, response_content_type: str) -> str:
    selected_type = (row["content_type"] or "").lower()
    if selected_type:
        return selected_type

    response_type = (response_content_type or "").lower()
    if "pdf" in response_type:
        return "pdf"
    if "spreadsheet" in response_type or "excel" in response_type:
        return "xlsx"
    if "wordprocessingml" in response_type:
        return "docx"
    if "msword" in response_type:
        return "doc"
    return content_type_from_url(row["url"])

