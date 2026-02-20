"""
Domain finder: tries to find the official domain for a company.
Strategy:
  1. Web search via requests + BeautifulSoup (Google / DuckDuckGo scraping)
  2. Fallback: guess slug.fr / slug.com and verify MX records
Results are cached in data/cache/domain_cache.json
"""

import json
import os
import re
import time
import random
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
import dns.resolver

from engine.normalize import company_to_slug

logger = logging.getLogger("b2b.domain_finder")

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "domain_cache.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Domains to ignore in results
IGNORE_DOMAINS = {
    "google.com", "google.fr", "facebook.com", "linkedin.com", "twitter.com",
    "youtube.com", "instagram.com", "wikipedia.org", "pinterest.com",
    "tiktok.com", "x.com", "reddit.com", "amazon.com", "yelp.com",
    "tripadvisor.com", "pagesjaunes.fr", "societe.com", "infogreffe.fr",
    "verif.com", "pappers.fr", "indeed.com", "glassdoor.com",
    "duckduckgo.com", "bing.com",
}


def _load_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _extract_domain(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        if host and "." in host and host not in IGNORE_DOMAINS:
            return host
    except Exception:
        pass
    return None


def _has_mx(domain: str) -> bool:
    """Check if domain has MX records."""
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        return False


def _search_duckduckgo(query: str, max_results: int = 5) -> list[str]:
    """
    Scrape DuckDuckGo HTML results.
    Returns list of URLs.
    """
    urls_found = []
    try:
        params = {"q": query, "t": "h_", "ia": "web"}
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.select("a.result__a"):
            href = a_tag.get("href", "")
            if href.startswith("http"):
                urls_found.append(href)
            if len(urls_found) >= max_results:
                break
    except Exception as e:
        logger.warning("DuckDuckGo search failed for '%s': %s", query, e)
    return urls_found


def find_domain(company: str, force_refresh: bool = False) -> str | None:
    """
    Find the email domain for a company.
    Returns domain string or None.
    """
    slug = company_to_slug(company)
    if not slug:
        return None

    cache = _load_cache()

    if not force_refresh and slug in cache:
        logger.info("Domain cache hit for '%s' -> %s", company, cache[slug])
        return cache[slug]

    logger.info("Searching domain for '%s' (slug=%s)...", company, slug)

    # Strategy 1: DuckDuckGo search
    queries = [
        f"{company} site officiel",
        f"{company} email contact",
    ]
    candidate_domains: dict[str, int] = {}

    for q in queries:
        urls = _search_duckduckgo(q)
        for url in urls:
            d = _extract_domain(url)
            if d:
                candidate_domains[d] = candidate_domains.get(d, 0) + 1
        time.sleep(random.uniform(0.5, 1.5))

    # Pick the most frequent non-ignored domain
    if candidate_domains:
        best = max(candidate_domains, key=candidate_domains.get)
        if _has_mx(best):
            cache[slug] = best
            _save_cache(cache)
            logger.info("Domain found via search for '%s': %s", company, best)
            return best

    # Strategy 2: Guess common domains
    for tld in (".fr", ".com", ".eu", ".io", ".net"):
        guess = slug + tld
        if _has_mx(guess):
            cache[slug] = guess
            _save_cache(cache)
            logger.info("Domain found via MX guess for '%s': %s", company, guess)
            return guess

    logger.warning("No domain found for '%s'", company)
    cache[slug] = None
    _save_cache(cache)
    return None
