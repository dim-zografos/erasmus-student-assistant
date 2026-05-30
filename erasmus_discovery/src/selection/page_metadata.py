from pathlib import PurePosixPath
from typing import Dict, List
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

from ..utils import compact_whitespace, content_type_from_url, get_url, is_document_resource, is_pdf_resource, truncate


def _resource_title_from_url(url: str) -> str:
    return unquote(PurePosixPath(urlparse(url).path).name).replace("_", " ").replace("-", " ").strip()


def fetch_page_metadata(url: str) -> Dict[str, object]:
    if is_pdf_resource(url):
        return {
            "title": _resource_title_from_url(url),
            "meta_description": "",
            "meta_keywords": "",
            "headings": ["PDF document"],
            "snippet": "",
            "content_type": "pdf",
        }

    if is_document_resource(url):
        return {
            "title": _resource_title_from_url(url),
            "meta_description": "",
            "meta_keywords": "",
            "headings": ["Document resource"],
            "snippet": "",
            "content_type": content_type_from_url(url),
        }

    try:
        response = get_url(url)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "title": "",
            "meta_description": "",
            "meta_keywords": "",
            "headings": [],
            "snippet": "",
            "content_type": "",
            "error": str(exc),
        }

    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = description_tag.get("content", "").strip() if description_tag else ""
    keywords_tag = soup.find("meta", attrs={"name": "keywords"})
    meta_keywords = keywords_tag.get("content", "").strip() if keywords_tag else ""

    headings: List[str] = []
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = heading.get_text(" ", strip=True)
        if text:
            headings.append(text)

    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()
    snippet = truncate(compact_whitespace(soup.get_text(" ", strip=True)), 1200)

    return {
        "title": title,
        "meta_description": meta_description,
        "meta_keywords": meta_keywords,
        "headings": headings[:20],
        "snippet": snippet,
        "content_type": response.headers.get("content-type", ""),
    }
