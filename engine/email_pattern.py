"""
Email pattern inference and email generation.

Supported patterns:
  prenom.nom       -> firstname.lastname@domain
  prenomnom        -> firstnamelastname@domain
  pnom             -> firstinitiallastname@domain
  p.nom            -> firstinitial.lastname@domain
  prenom           -> firstname@domain
  nom.prenom       -> lastname.firstname@domain
  nom              -> lastname@domain
  nomp             -> lastnamefirstinitial@domain
  prenom_nom       -> firstname_lastname@domain

Scoring is based on frequency of each pattern among discovered emails.
"""

import json
import os
import re
import logging
from collections import Counter

from engine.normalize import normalize_name_part, name_variants

logger = logging.getLogger("b2b.email_pattern")

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "pattern_cache.json")

# Patterns with their template function
# Each returns (local_part, pattern_name)
PATTERN_DEFS = [
    ("prenom.nom",    lambda f, l: f"{f}.{l}"),
    ("prenomnom",     lambda f, l: f"{f}{l}"),
    ("pnom",          lambda f, l: f"{f[0]}{l}" if f else l),
    ("p.nom",         lambda f, l: f"{f[0]}.{l}" if f else l),
    ("prenom",        lambda f, l: f),
    ("nom.prenom",    lambda f, l: f"{l}.{f}"),
    ("nom",           lambda f, l: l),
    ("nomp",          lambda f, l: f"{l}{f[0]}" if f else l),
    ("prenom_nom",    lambda f, l: f"{f}_{l}"),
]


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


def _guess_pattern_for_email(local: str) -> list[str]:
    """
    Try to identify which pattern(s) could produce a given local part.
    Heuristic: check structural features.
    """
    patterns = []
    if "." in local:
        parts = local.split(".")
        if len(parts) == 2:
            a, b = parts
            if len(a) == 1:
                patterns.append("p.nom")
            elif len(b) == 1:
                # could be nom.p -- rare, skip
                pass
            else:
                # Could be prenom.nom or nom.prenom -- we assume prenom.nom by default
                patterns.append("prenom.nom")
                patterns.append("nom.prenom")
    elif "_" in local:
        patterns.append("prenom_nom")
    else:
        # No separator
        if len(local) <= 2:
            patterns.append("prenom")
        elif local[-1:].isalpha() and len(local) > 3:
            patterns.append("prenomnom")
            patterns.append("pnom")
            patterns.append("nomp")
            patterns.append("prenom")
            patterns.append("nom")

    return patterns if patterns else ["prenomnom"]


def infer_pattern(domain: str, emails: list[str], force_refresh: bool = False) -> tuple[str, float, str]:
    """
    Given a domain and discovered emails, infer the most likely pattern.

    Returns: (pattern_name, confidence, debug_info)
    confidence is 0-1.
    """
    cache = _load_cache()
    cache_key = domain

    if not force_refresh and cache_key in cache:
        entry = cache[cache_key]
        return entry["pattern"], entry["confidence"], entry.get("debug", "from cache")

    if not emails:
        logger.info("No emails to infer pattern for %s", domain)
        return ("prenom.nom", 0.2, "default fallback, no emails found")

    # Filter to domain
    domain_emails = [e for e in emails if e.endswith(f"@{domain}")]
    if not domain_emails:
        return ("prenom.nom", 0.2, "no emails match domain")

    # Count pattern guesses
    pattern_votes: Counter = Counter()
    for email in domain_emails:
        local = email.split("@")[0]
        guesses = _guess_pattern_for_email(local)
        for g in guesses:
            pattern_votes[g] += 1

    if not pattern_votes:
        return ("prenom.nom", 0.2, "could not infer")

    best_pattern = pattern_votes.most_common(1)[0][0]
    total_votes = sum(pattern_votes.values())
    best_count = pattern_votes[best_pattern]
    confidence = round(min(1.0, (best_count / max(total_votes, 1)) * 0.7 + len(domain_emails) * 0.05), 2)
    confidence = min(confidence, 0.95)

    debug = f"votes={dict(pattern_votes)}, emails_found={len(domain_emails)}"
    logger.info("Pattern for %s: %s (confidence=%.2f)", domain, best_pattern, confidence)

    # Cache
    cache[cache_key] = {"pattern": best_pattern, "confidence": confidence, "debug": debug}
    _save_cache(cache)

    return (best_pattern, confidence, debug)


def generate_email(firstname: str, lastname: str, domain: str, pattern: str) -> str | None:
    """
    Generate an email address for the given name and pattern.
    """
    f = normalize_name_part(firstname)
    l = normalize_name_part(lastname)

    if not f or not l or not domain:
        return None

    for pname, func in PATTERN_DEFS:
        if pname == pattern:
            local = func(f, l)
            return f"{local}@{domain}"

    # Default
    return f"{f}.{l}@{domain}"
