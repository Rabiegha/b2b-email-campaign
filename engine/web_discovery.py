"""
Web discovery: crawl public pages of a domain to extract email addresses.
Used to infer the email pattern for a company.
Multi-strategy: direct site crawl + DuckDuckGo search + Google cache.
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

# Generic / role emails to exclude from pattern inference
GENERIC_LOCALS = {
    "contact", "info", "hello", "bonjour", "support", "admin", "commercial",
    "direction", "communication", "marketing", "rh", "recrutement", "emploi",
    "sales", "billing", "facturation", "comptabilite", "compta", "presse",
    "accueil", "reception", "service", "webmaster", "postmaster", "noreply",
    "no-reply", "newsletter", "abuse", "privacy", "dpo", "rgpd",
}


def _is_personal_email(email: str) -> bool:
    """Return True if the email looks like a personal (non-generic) address."""
    local = email.split("@")[0].lower()
    return local not in GENERIC_LOCALS and len(local) > 1


def _fetch_page(url: str, timeout: int = 8) -> str | None:
    """Fetch a page and return its HTML, or None on error."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout,
                            allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", url, e)
    return None


def _extract_emails(html: str, target_domain: str) -> list[str]:
    """Extract emails matching target_domain from HTML."""
    if not html:
        return []
    found = EMAIL_RE.findall(html)
    emails = []
    for e in found:
        e_lower = e.lower()
        if e_lower.endswith(f"@{target_domain}"):
            emails.append(e_lower)
    return emails


def _extract_internal_links(html: str, domain: str) -> list[str]:
    """Extract internal links from HTML."""
    links = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Normalize relative links
            if href.startswith("/"):
                href = f"https://{domain}{href}"
            elif not href.startswith("http"):
                continue

            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host == domain:
                links.append(href)
    except Exception:
        pass
    return links


def _crawl_site(domain: str, max_pages: int = 15) -> list[str]:
    """
    Crawl the site directly to find pages likely containing emails.
    Start from homepage and known paths, then follow links.
    """
    # Candidate pages to try (prioritised)
    candidates = []

    # Key pages that often have emails
    key_paths = [
        "/", "/contact", "/contactez-nous", "/nous-contacter",
        "/equipe", "/team", "/notre-equipe", "/about", "/a-propos",
        "/mentions-legales", "/legal", "/mentions",
        "/qui-sommes-nous", "/about-us",
        "/leadership", "/dirigeants", "/direction",
    ]

    for path in key_paths:
        candidates.append(f"https://{domain}{path}")
        candidates.append(f"https://www.{domain}{path}")

    # Deduplicate
    seen = set()
    ordered = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    # Phase 1: Fetch key pages, collect emails + discover more links
    all_emails = set()
    more_links = []

    for url in ordered[:max_pages]:
        html = _fetch_page(url)
        if html:
            emails = _extract_emails(html, domain)
            all_emails.update(emails)
            # Also follow internal links from homepage
            if url.rstrip("/").endswith(domain) or url.rstrip("/").endswith(f"www.{domain}"):
                links = _extract_internal_links(html, domain)
                more_links.extend(links)
        time.sleep(random.uniform(0.2, 0.5))

    # Phase 2: Follow discovered links (prioritise those with keywords)
    email_keywords = {"contact", "equipe", "team", "about", "legal", "mention",
                      "qui-sommes", "direction", "leadership", "staff", "people"}

    scored_links = []
    for link in more_links:
        if link in seen:
            continue
        seen.add(link)
        path_lower = urlparse(link).path.lower()
        score = sum(1 for kw in email_keywords if kw in path_lower)
        scored_links.append((score, link))

    scored_links.sort(key=lambda x: -x[0])

    for _, url in scored_links[:max_pages - len(ordered)]:
        html = _fetch_page(url)
        if html:
            emails = _extract_emails(html, domain)
            all_emails.update(emails)
        time.sleep(random.uniform(0.2, 0.5))

    return sorted(all_emails)


def _search_duckduckgo(domain: str, max_results: int = 5) -> list[str]:
    """
    Find pages likely to contain emails by scraping DuckDuckGo.
    """
    urls = []
    queries = [
        f"site:{domain} contact email",
        f"site:{domain} @{domain}",
        f"site:{domain} equipe team",
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
            logger.warning("DuckDuckGo search failed: %s", e)
        if len(urls) >= max_results:
            break
        time.sleep(random.uniform(0.5, 1.2))
    return urls


def _search_external_email_mentions(domain: str) -> list[str]:
    """
    Search for email addresses of the domain mentioned on external sites
    (LinkedIn, directories, etc.)
    """
    emails = set()
    queries = [
        f'"@{domain}" email',
        f'"@{domain}" contact',
    ]
    for q in queries:
        try:
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": q, "t": "h_", "ia": "web"},
                headers=HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                found = EMAIL_RE.findall(resp.text)
                for e in found:
                    e_lower = e.lower()
                    if e_lower.endswith(f"@{domain}"):
                        emails.add(e_lower)
        except Exception as e:
            logger.debug("External search failed: %s", e)
        time.sleep(random.uniform(0.5, 1.0))
    return sorted(emails)


def discover_emails(domain: str, max_pages: int = 15) -> list[str]:
    """
    Discover email addresses for a domain using multiple strategies:
    1. Direct site crawl (homepage, /contact, /equipe, etc. + follow links)
    2. DuckDuckGo search for pages on the domain
    3. External mentions of @domain emails
    Returns deduplicated list of personal emails (excludes generic contacts).
    """
    if not domain:
        return []

    logger.info("Discovering emails for domain=%s", domain)
    all_emails = set()

    # Strategy 1: Direct crawl (most reliable)
    crawled = _crawl_site(domain, max_pages=max_pages)
    all_emails.update(crawled)
    logger.info("Direct crawl found %d emails for %s", len(crawled), domain)

    # Strategy 2: DuckDuckGo pages (if crawl found < 2 personal emails)
    personal_so_far = [e for e in all_emails if _is_personal_email(e)]
    if len(personal_so_far) < 2:
        ddg_urls = _search_duckduckgo(domain, max_results=5)
        for url in ddg_urls:
            html = _fetch_page(url)
            if html:
                emails = _extract_emails(html, domain)
                all_emails.update(emails)
            time.sleep(random.uniform(0.3, 0.6))

    # Strategy 3: External mentions
    personal_so_far = [e for e in all_emails if _is_personal_email(e)]
    if len(personal_so_far) < 2:
        external = _search_external_email_mentions(domain)
        all_emails.update(external)
        logger.info("External search found %d more emails for %s",
                     len(external), domain)

    # Filter: keep only personal emails for pattern inference
    personal_emails = [e for e in sorted(all_emails) if _is_personal_email(e)]
    all_sorted = sorted(all_emails)

    logger.info("Total found %d emails (%d personal) for %s",
                len(all_sorted), len(personal_emails), domain)

    # Return personal emails first, then all
    # Pattern inference will use personal emails preferentially
    return personal_emails if personal_emails else all_sorted
