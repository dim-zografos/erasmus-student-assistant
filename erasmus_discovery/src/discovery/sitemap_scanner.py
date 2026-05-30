import xml.etree.ElementTree as ET
from typing import List, Set
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from ..core.models import DiscoveredUrl, UniversityConfig
from ..storage.database import insert_discovered_url, log_event
from ..utils import content_type_from_url, get_url, is_allowed_url, normalize_url
from .robots_parser import get_robots_sitemaps


def _candidate_sitemaps(university: UniversityConfig) -> List[str]:
    base = university.base_erasmus_url.rstrip("/") + "/"
    parsed = urlparse(university.base_erasmus_url)
    root = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
    candidates = [
        urljoin(base, "sitemap.xml"),
        urljoin(base, "sitemap_index.xml"),
        urljoin(root, "sitemap.xml"),
        urljoin(root, "sitemap_index.xml"),
    ]
    candidates.extend(get_robots_sitemaps(university.base_erasmus_url))
    return list(dict.fromkeys(candidates))


def _xml_locs(xml_text: str) -> List[str]:
    root = ET.fromstring(xml_text)
    locs: List[str] = []
    for element in root.iter():
        if element.tag.endswith("loc") and element.text:
            locs.append(element.text.strip())
    return locs


def _fetch_sitemap(url: str) -> str:
    response = get_url(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "xml" not in content_type and not response.text.lstrip().startswith("<"):
        raise ValueError("Response is not XML")
    return response.text


def scan_sitemaps(conn, university: UniversityConfig, max_sitemaps: int = 20) -> int:
    visited: Set[str] = set()
    queue = _candidate_sitemaps(university)
    discovered_count = 0

    while queue and len(visited) < max_sitemaps:
        sitemap_url = normalize_url(queue.pop(0))
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        try:
            xml_text = _fetch_sitemap(sitemap_url)
            locs = _xml_locs(xml_text)
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            log_event(conn, "sitemap", "skipped", str(exc), university.key, sitemap_url)
            continue

        for loc in locs:
            normalized = normalize_url(loc)
            if normalized.endswith(".xml") and is_allowed_url(normalized, university.allowed_domains):
                if normalized not in visited:
                    queue.append(normalized)
                continue
            if not is_allowed_url(normalized, university.allowed_domains):
                continue
            insert_discovered_url(
                conn,
                DiscoveredUrl(
                    university_key=university.key,
                    url=normalized,
                    content_type=content_type_from_url(normalized),
                    depth=0,
                    discovered_from=sitemap_url,
                    status="discovered",
                ),
            )
            discovered_count += 1

    if discovered_count:
        log_event(conn, "sitemap", "ok", f"Discovered {discovered_count} URLs", university.key)
    else:
        log_event(conn, "sitemap", "no_urls", "No sitemap URLs found; fallback crawler can be used", university.key)
    return discovered_count
