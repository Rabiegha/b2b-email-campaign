"""
Email verifier – checks if an email address actually exists.

Strategies (in order):
  1. Hunter.io API   – if HUNTER_API_KEY is set, use domain-search + email-verify
  2. SMTP RCPT TO    – connect to the MX server, issue RCPT TO and read response
  3. Catch-all check – detect catch-all domains so we don't over-trust SMTP results

The module also exposes `find_best_email()` which generates all pattern candidates
and returns the one that passes verification with the highest confidence.
"""

import os
import re
import smtplib
import socket
import logging
import time
import random
from typing import Optional

import dns.resolver
import requests

from engine.normalize import normalize_name_part

logger = logging.getLogger("b2b.email_verifier")

# ── Hunter.io ──────────────────────────────────────────────────────────────

def _hunter_api_key() -> str | None:
    return os.getenv("HUNTER_API_KEY") or None


def hunter_domain_search(domain: str) -> dict | None:
    """
    Call Hunter.io /domain-search to get the email pattern and emails
    for a domain.  Returns {"pattern": ..., "emails": [...], "confidence": ...}
    or None if unavailable.
    """
    key = _hunter_api_key()
    if not key:
        return None

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": key},
            timeout=10,
        )
        if resp.status_code == 401:
            logger.warning("Hunter.io: invalid API key")
            return None
        if resp.status_code == 429:
            logger.warning("Hunter.io: rate limited")
            return None
        if resp.status_code != 200:
            return None

        data = resp.json().get("data", {})
        pattern = data.get("pattern")            # e.g. "{first}.{last}"
        emails_raw = data.get("emails", [])
        emails = [e["value"] for e in emails_raw if e.get("value")]

        # Map Hunter pattern names to ours
        pattern_map = {
            "{first}.{last}": "prenom.nom",
            "{first}{last}": "prenomnom",
            "{f}{last}": "pnom",
            "{f}.{last}": "p.nom",
            "{first}": "prenom",
            "{last}.{first}": "nom.prenom",
            "{last}": "nom",
            "{last}{f}": "nomp",
            "{first}_{last}": "prenom_nom",
        }

        our_pattern = pattern_map.get(pattern, "prenom.nom")

        # Confidence from Hunter is out of 100
        org_confidence = data.get("organization", None)

        return {
            "pattern": our_pattern,
            "emails": emails,
            "confidence": 0.85,   # Hunter is generally very reliable
            "source": "hunter.io",
            "raw_pattern": pattern,
        }
    except Exception as e:
        logger.warning("Hunter.io error: %s", e)
        return None


def hunter_verify_email(email: str) -> dict | None:
    """
    Use Hunter.io /email-verifier to check if an email is deliverable.
    Returns {"result": "deliverable"|"undeliverable"|"risky"|"unknown", "score": int}
    """
    key = _hunter_api_key()
    if not key:
        return None

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": key},
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json().get("data", {})
        return {
            "result": data.get("result", "unknown"),
            "score": data.get("score", 0),
            "smtp_check": data.get("smtp_check", False),
        }
    except Exception as e:
        logger.debug("Hunter verify error: %s", e)
        return None


# ── MX / SMTP verification ────────────────────────────────────────────────

def _get_mx_host(domain: str) -> str | None:
    """Resolve the primary MX host for a domain."""
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_records = sorted(answers, key=lambda r: r.preference)
        if mx_records:
            host = str(mx_records[0].exchange).rstrip(".")
            return host
    except Exception as e:
        logger.debug("MX lookup failed for %s: %s", domain, e)
    return None


def smtp_check_email(email: str, sender: str = "check@example.com",
                     timeout: int = 10) -> str:
    """
    Check if an email exists via SMTP RCPT TO.

    Returns:
      "valid"       – server accepted the recipient (250)
      "invalid"     – server rejected the recipient (550, 553, etc.)
      "catch_all"   – server accepts everything (detected via probe)
      "unknown"     – could not determine (greylisting, timeout, etc.)
    """
    domain = email.split("@")[1]
    mx_host = _get_mx_host(domain)
    if not mx_host:
        return "unknown"

    try:
        smtp = smtplib.SMTP(timeout=timeout)
        smtp.connect(mx_host, 25)
        smtp.ehlo("mail.example.com")

        # Some servers require STARTTLS
        try:
            smtp.starttls()
            smtp.ehlo("mail.example.com")
        except smtplib.SMTPException:
            pass  # Not all servers support STARTTLS on port 25

        smtp.mail(sender)
        code, _ = smtp.rcpt(email)
        smtp.quit()

        if code == 250:
            return "valid"
        elif code in (550, 551, 552, 553, 554):
            return "invalid"
        else:
            return "unknown"

    except smtplib.SMTPServerDisconnected:
        return "unknown"
    except smtplib.SMTPConnectError:
        return "unknown"
    except (socket.timeout, socket.error):
        return "unknown"
    except Exception as e:
        logger.debug("SMTP check failed for %s: %s", email, e)
        return "unknown"


def _is_catch_all(domain: str) -> bool:
    """
    Test if the domain is a catch-all by sending RCPT TO a random address.
    If the server accepts a clearly fake address, it's catch-all.
    """
    fake_local = f"zzztest{random.randint(10000,99999)}"
    fake_email = f"{fake_local}@{domain}"
    result = smtp_check_email(fake_email)
    return result == "valid"


# ── Main: find best email ─────────────────────────────────────────────────

# Import PATTERN_DEFS here to avoid circular imports
def _get_pattern_defs():
    from engine.email_pattern import PATTERN_DEFS
    return PATTERN_DEFS


def find_best_email(
    firstname: str,
    lastname: str,
    domain: str,
    known_pattern: str | None = None,
    skip_smtp: bool = False,
) -> tuple[str | None, str, float, str]:
    """
    Find the best email for a person at a domain.

    Strategy:
      1. If Hunter.io API key is set → use Hunter domain-search
      2. Generate candidates for all patterns
      3. SMTP-verify each candidate (unless skip_smtp=True)
      4. Return the best match

    Returns: (email, pattern, confidence, debug_info)
    """
    f = normalize_name_part(firstname)
    l = normalize_name_part(lastname)

    if not f or not l or not domain:
        return (None, "prenom.nom", 0.0, "nom/prénom/domaine manquant")

    PATTERN_DEFS = _get_pattern_defs()

    # ── Strategy 1: Hunter.io ──────────────────────────────
    hunter_result = hunter_domain_search(domain)
    if hunter_result:
        pattern = hunter_result["pattern"]
        # Generate email using Hunter's pattern
        for pname, func in PATTERN_DEFS:
            if pname == pattern:
                email = f"{func(f, l)}@{domain}"
                break
        else:
            email = f"{f}.{l}@{domain}"

        # Optionally verify via Hunter
        verification = hunter_verify_email(email)
        if verification:
            if verification["result"] == "deliverable":
                return (email, pattern, 0.95, f"Hunter.io: vérifié ({verification['score']}%)")
            elif verification["result"] == "undeliverable":
                # Try other patterns via SMTP
                logger.info("Hunter pattern %s rejected for %s %s, trying SMTP", pattern, firstname, lastname)
            else:
                return (email, pattern, 0.80, f"Hunter.io: {verification['result']}")
        else:
            return (email, pattern, hunter_result["confidence"],
                    f"Hunter.io: pattern={hunter_result['raw_pattern']}")

    # ── Strategy 2: Generate all candidates ────────────────
    candidates = []
    # Prioritise known pattern if we have one
    if known_pattern:
        priority_order = [known_pattern] + [p for p, _ in PATTERN_DEFS if p != known_pattern]
    else:
        # Most common patterns first
        priority_order = [
            "prenom.nom", "p.nom", "prenomnom", "pnom",
            "prenom_nom", "nom.prenom", "prenom", "nom", "nomp",
        ]

    for pname in priority_order:
        for p, func in PATTERN_DEFS:
            if p == pname:
                try:
                    local = func(f, l)
                    candidates.append((pname, f"{local}@{domain}"))
                except (IndexError, TypeError):
                    pass
                break

    if not candidates:
        return (None, "prenom.nom", 0.0, "impossible de générer des candidats")

    # ── Strategy 3: SMTP verification ──────────────────────
    if skip_smtp:
        # No SMTP check – return the first candidate (most likely pattern)
        email = candidates[0][1]
        pattern = candidates[0][0]
        conf = 0.50 if pattern == "prenom.nom" else 0.40
        return (email, pattern, conf, "pas de vérification SMTP")

    # Check if domain is catch-all first
    catch_all = _is_catch_all(domain)
    if catch_all:
        # All emails will appear valid, can't distinguish
        email = candidates[0][1]
        pattern = candidates[0][0]
        conf = 0.55 if pattern == "prenom.nom" else 0.45
        return (email, pattern, conf, "domaine catch-all (SMTP non fiable)")

    # Try each candidate via SMTP
    valid_candidates = []
    invalid_count = 0

    for pname, email in candidates:
        result = smtp_check_email(email)
        time.sleep(random.uniform(0.3, 0.8))  # polite delay

        if result == "valid":
            valid_candidates.append((pname, email))
            # First valid is almost certainly correct
            break
        elif result == "invalid":
            invalid_count += 1
        # "unknown" → skip, server might be uncooperative

    if valid_candidates:
        best_pattern, best_email = valid_candidates[0]
        # More invalid candidates we saw before finding the valid one
        # = more certainty this is the right one
        conf = min(0.95, 0.75 + invalid_count * 0.05)
        debug = f"SMTP vérifié ({invalid_count} invalides rejetés avant)"
        return (best_email, best_pattern, conf, debug)

    # SMTP didn't help (all unknown) → fall back to most likely pattern
    email = candidates[0][1]
    pattern = candidates[0][0]
    conf = 0.50 if pattern == "prenom.nom" else 0.40
    return (email, pattern, conf, f"SMTP inconcluant ({invalid_count} invalides)")
