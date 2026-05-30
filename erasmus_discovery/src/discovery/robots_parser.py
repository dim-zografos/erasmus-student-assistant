from typing import List
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from ..utils import get_url


def get_robots_sitemaps(base_url: str) -> List[str]:
    parsed = urlparse(base_url)
    root_url = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
    robots_urls = [
        urljoin(base_url.rstrip("/") + "/", "robots.txt"),
        urljoin(root_url, "robots.txt"),
    ]

    sitemaps: List[str] = []
    for robots_url in dict.fromkeys(robots_urls):
        try:
            response = get_url(robots_url)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue

        for line in response.text.splitlines():
            if line.lower().startswith("sitemap:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    sitemaps.append(value)
    return list(dict.fromkeys(sitemaps))
