import time
from collections import deque
from typing import Set

import requests
from bs4 import BeautifulSoup

from ..core.models import DiscoveredUrl, UniversityConfig
from ..storage.database import insert_discovered_url, log_event
from ..utils import (
    content_type_from_url,
    get_url,
    is_allowed_url,
    is_document_resource,
    is_skippable_href,
    normalize_url,
)


def crawl_university(
    conn,
    university: UniversityConfig,
    max_depth: int = 2,
    max_pages_per_university: int = 100,
    delay_seconds: float = 0.4,
) -> int:
    start_url = normalize_url(university.base_erasmus_url)
    queue = deque([(start_url, 0, "")])
    visited: Set[str] = set()
    discovered_count = 0

    while queue and len(visited) < max_pages_per_university:
        url, depth, discovered_from = queue.popleft()
        if url in visited or depth > max_depth:
            continue
        if not is_allowed_url(url, university.allowed_domains):
            continue

        visited.add(url)
        insert_discovered_url(
            conn,
            DiscoveredUrl(
                university_key=university.key,
                url=url,
                content_type=content_type_from_url(url),
                depth=depth,
                discovered_from=discovered_from,
                status="discovered",
            ),
        )
        discovered_count += 1

        if is_document_resource(url) or depth == max_depth:
            continue

        try:
            response = get_url(url)
            if response.status_code >= 400:
                log_event(conn, "fallback_crawler", "http_error", str(response.status_code), university.key, url)
                continue
            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type:
                continue
        except requests.RequestException as exc:
            log_event(conn, "fallback_crawler", "error", str(exc), university.key, url)
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if is_skippable_href(href):
                continue
            next_url = normalize_url(href, url)
            if not is_allowed_url(next_url, university.allowed_domains):
                continue

            insert_discovered_url(
                conn,
                DiscoveredUrl(
                    university_key=university.key,
                    url=next_url,
                    title=link.get_text(" ", strip=True)[:200],
                    content_type=content_type_from_url(next_url),
                    depth=depth + 1,
                    discovered_from=url,
                    status="discovered",
                ),
            )
            if next_url not in visited and not is_document_resource(next_url):
                queue.append((next_url, depth + 1, url))

        time.sleep(delay_seconds)

    log_event(conn, "fallback_crawler", "ok", f"Discovered {discovered_count} crawled pages/resources", university.key)
    return discovered_count
