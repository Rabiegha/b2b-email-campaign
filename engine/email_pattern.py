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
                # nom.p -> rare, skip
                pass
            else:
                # Could be prenom.nom or nom.prenom
                patterns.append("prenom.nom")
                patterns.append("nom.prenom")
    elif "_" in local:
        parts = local.split("_")
        if len(parts) == 2:
            patterns.append("prenom_nom")
    else:
        # No separator
        if len(local) <= 1:
            pass
        elif len(local) == 2:
            patterns.append("pnom")
        elif len(local) <= 4:
            patterns.append("pnom")
            patterns.append("nom")
            patterns.append("prenom")
        else:
            # Most likely prenomnom (e.g. jeandupont)
            patterns.append("prenomnom")
            # Less likely alternatives
            patterns.append("pnom")

    return patterns if patterns else ["prenomnom"]


def _match_email_to_pattern(email_local: str, known_first: str = None,
                             known_last: str = None) -> list[str]:
    """
    If we know the first/last name of the person, match the email to
    specific patterns with higher confidence.
    """
    if not known_first or not known_last:
        return _guess_pattern_for_email(email_local)

    f = normalize_name_part(known_first)
    l = normalize_name_part(known_last)
    matched = []

    for pname, func in PATTERN_DEFS:
        try:
            expected = func(f, l)
            if expected == email_local:
                matched.append(pname)
        except (IndexError, TypeError):
            continue

    return matched if matched else _guess_pattern_for_email(email_local)


def infer_pattern(domain: str, emails: list[str],
                  known_names: list[tuple[str, str]] | None = None,
                  force_refresh: bool = False) -> tuple[str, float, str]:
    """
    Given a domain and discovered emails, infer the most likely pattern.
    known_names: optional list of (firstname, lastname) tuples for exact matching.

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
        # prenom.nom is statistically the most common pattern (~70%)
        return ("prenom.nom", 0.50, "prenom.nom par défaut (pattern le plus fréquent)")

    # Filter to domain
    domain_emails = [e for e in emails if e.endswith(f"@{domain}")]
    if not domain_emails:
        return ("prenom.nom", 0.50, "prenom.nom par défaut (aucun email du domaine trouvé)")

    # Prepare normalised known names for exact matching
    norm_names = []
    if known_names:
        for first, last in known_names:
            if first and last:
                norm_names.append((normalize_name_part(first), normalize_name_part(last)))

    # Count pattern guesses – prefer exact name matching when possible
    pattern_votes: Counter = Counter()
    exact_matches = 0
    strong_matches = 0

    for email in domain_emails:
        local = email.split("@")[0]

        # --- Try exact matching against known names ---
        exact_guesses = None
        if norm_names:
            for f, l in norm_names:
                matched = []
                for pname, func in PATTERN_DEFS:
                    try:
                        if func(f, l) == local:
                            matched.append(pname)
                    except (IndexError, TypeError):
                        continue
                if matched:
                    exact_guesses = matched
                    exact_matches += 1
                    break  # first name-pair that matches is enough

        if exact_guesses:
            # Exact name match – very strong signal
            if len(exact_guesses) == 1:
                pattern_votes[exact_guesses[0]] += 5
                strong_matches += 1
            else:
                for g in exact_guesses:
                    pattern_votes[g] += 3
        else:
            # Fallback to structural guessing
            guesses = _guess_pattern_for_email(local)
            if len(guesses) == 1:
                pattern_votes[guesses[0]] += 3
                strong_matches += 1
            elif len(guesses) == 2:
                for g in guesses:
                    pattern_votes[g] += 2
            else:
                for g in guesses:
                    pattern_votes[g] += 1

    if not pattern_votes:
        return ("prenom.nom", 0.15, "could not infer")

    best_pattern = pattern_votes.most_common(1)[0][0]
    best_count = pattern_votes[best_pattern]
    total_votes = sum(pattern_votes.values())

    # Confidence formula
    vote_ratio = best_count / max(total_votes, 1)

    # Base: proportion of votes for best pattern (0‑0.45)
    base = vote_ratio * 0.45

    # Volume bonus: more emails found → more reliable (0‑0.20)
    email_bonus = min(0.20, len(domain_emails) * 0.12)

    # Exact‑match bonus: matched against real names (0‑0.30)
    exact_bonus = min(0.30, exact_matches * 0.20)

    # Strong‑match bonus: unambiguous patterns (0‑0.15)
    strong_bonus = min(0.15, strong_matches * 0.10)

    # Statistical prior: prenom.nom is the most common pattern
    prior_bonus = 0.10 if best_pattern == "prenom.nom" else 0.0

    confidence = round(min(0.95, base + email_bonus + exact_bonus + strong_bonus + prior_bonus), 2)
    confidence = max(confidence, 0.35)  # minimum 35% when we have some evidence

    debug = (f"votes={dict(pattern_votes)}, emails_found={len(domain_emails)}, "
             f"exact={exact_matches}, strong={strong_matches}")
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
