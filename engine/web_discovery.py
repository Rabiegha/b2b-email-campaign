"""
Web discovery: crawl public pages of a domain to extract email addresses.
Used to infer the email pattern for a company.
"""

import re
import time
import random
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("b2b.web_discovery")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _search_pages(domain: str, max_results: int = 5) -> list[str]:
    """
    Find pages likely to contain emails by scraping DuckDuckGo.
    """
    urls = []
    queries = [
        f"site:{domain} contact email",
        f"site:{domain} @{domain}",
        f"site:{domain} equipe",
    ]
    for q in queries:
        try:
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": q, "t": "h_", "ia": "web"},
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a.result__a"):
                href = a.get("href", "")
                if href.startswith("http") and domain in href:
                    urls.append(href)
                if len(urls) >= max_results:
                    break
        except Exception as e:
            logger.warning("Search page query failed: %s", e)
        if len(urls) >= max_results:
            break
        time.sleep(random.uniform(0.5, 1.2))

    # Also try obvious pages
    for path in ("/contact", "/equipe", "/team", "/about", "/mentions-legales"):
        urls.append(f"https://{domain}{path}")
        urls.append(f"https://www.{domain}{path}")

    # Deduplicate
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique[:max_results + 6]


def _fetch_emails_from_page(url: str, target_domain: str) -> list[str]:
    """Fetch a page and extract emails matching target_domain."""
    emails = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if resp.status_code == 200:
            found = EMAIL_RE.findall(resp.text)
            for e in found:
                e_lower = e.lower()
                if e_lower.endswith(f"@{target_domain}"):
                    emails.append(e_lower)
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", url, e)
    return emails


def discover_emails(domain: str, max_pages: int = 10) -> list[str]:
    """
    Discover email addresses on public pages of a domain.
    Returns deduplicated list of emails.
    """
    if not domain:
        return []

    logger.info("Discovering emails for domain=%s", domain)
    pages = _search_pages(domain, max_results=max_pages)
    all_emails = set()

    for url in pages[:max_pages]:
        found = _fetch_emails_from_page(url, domain)
        all_emails.update(found)
        time.sleep(random.uniform(0.3, 0.8))

    result = sorted(all_emails)
    logger.info("Found %d emails for %s: %s", len(result), domain, result[:10])
    return result
