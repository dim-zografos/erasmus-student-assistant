import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List
from urllib.parse import urldefrag, urljoin, urlparse

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "universities.json"
DB_PATH = PROJECT_ROOT / "data" / "erasmus.db"

USER_AGENT = "UTH-Erasmus-Discovery/1.0 (+university assignment)"
REQUEST_TIMEOUT = 15

urllib3.disable_warnings(InsecureRequestWarning)


def get_url(url: str, **kwargs) -> requests.Response:
    """Fetch a URL, retrying only certificate-chain failures without verification."""
    headers = kwargs.pop("headers", None) or {"User-Agent": USER_AGENT}
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT)
    try:
        return requests.get(url, headers=headers, timeout=timeout, **kwargs)
    except requests.exceptions.SSLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        return requests.get(url, headers=headers, timeout=timeout, verify=False, **kwargs)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_directories() -> None:
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)


def normalize_url(url: str, base_url: str = "") -> str:
    if base_url:
        url = urljoin(base_url, url)
    url, _fragment = urldefrag(url)
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        return url
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return parsed._replace(scheme=scheme, netloc=netloc, path=path).geturl()


def is_allowed_url(url: str, allowed_domains: Iterable[str]) -> bool:
    host = urlparse(url).netloc.lower()
    allowed = [domain.lower() for domain in allowed_domains]
    return any(host == domain or host.endswith("." + domain) for domain in allowed)


def is_skippable_href(href: str) -> bool:
    value = (href or "").strip().lower()
    return (
        not value
        or value.startswith("#")
        or value.startswith("mailto:")
        or value.startswith("tel:")
        or value.startswith("javascript:")
    )


def content_type_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith(".xls"):
        return "xls"
    if path.endswith(".xlsx"):
        return "xlsx"
    if path.endswith(".docx"):
        return "docx"
    if path.endswith(".doc"):
        return "doc"
    return "html"


def is_document_resource(url: str) -> bool:
    return content_type_from_url(url) in {"pdf", "xls", "xlsx", "doc", "docx"}


def is_pdf_resource(url: str) -> bool:
    return content_type_from_url(url) == "pdf"


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def hash_values(values: Iterable[Any]) -> str:
    joined = "|".join("" if value is None else str(value) for value in values)
    return hash_text(joined)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads_list(value: str) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def compact_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def clean_model_text(text: str) -> str:
    text = text or ""
    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>", start) + len("</think>")
        text = text[:start] + text[end:]
    return text.strip()
