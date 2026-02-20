"""
Outbox builder: merges email suggestions with messages to create
the outbox (send queue). Handles deduplication, validation, status assignment.
"""

import logging
import re
from engine import db
from engine.normalize import normalize_company

logger = logging.getLogger("b2b.outbox")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(EMAIL_RE.match(email.strip()))


def build_outbox(conn) -> dict:
    """
    Build the outbox by merging email_suggestions with messages via company_key.

    Returns dict with stats: {ready: int, error: int, skipped_duplicates: int, details: list}
    """
    logger.info("Building outbox...")

    # Clear existing outbox
    db.clear_outbox(conn)

    # Load suggestions (join with prospects)
    suggestions = conn.execute("""
        SELECT es.suggested_email, es.confidence_score, es.status AS es_status,
               p.id AS prospect_id, p.firstname, p.lastname,
               p.company, p.company_key
        FROM email_suggestions es
        JOIN prospects p ON p.id = es.prospect_id
        ORDER BY es.confidence_score DESC
    """).fetchall()

    # Load messages indexed by company_key
    messages_rows = db.get_all_messages(conn)
    messages_by_key: dict[str, dict] = {}
    for m in messages_rows:
        key = m["company_key"]
        if key not in messages_by_key:
            messages_by_key[key] = {
                "company": m["company"],
                "subject": m["subject"],
                "body_text": m["body_text"],
            }

    stats = {"ready": 0, "error": 0, "skipped_duplicates": 0, "details": []}
    seen_emails: set[str] = set()

    for s in suggestions:
        email = (s["suggested_email"] or "").strip().lower()
        company_key = s["company_key"]
        company = s["company"]
        firstname = s["firstname"]
        lastname = s["lastname"]

        # Deduplication
        if email and email in seen_emails:
            stats["skipped_duplicates"] += 1
            logger.info("Duplicate email skipped: %s", email)
            stats["details"].append({
                "company": company, "email": email,
                "status": "SKIPPED", "reason": "DUPLICATE_EMAIL"
            })
            continue

        # Determine status and error
        error_parts = []

        if not email or s["es_status"] == "NOT_FOUND":
            error_parts.append("EMAIL_NOT_FOUND")
        elif not _is_valid_email(email):
            error_parts.append("INVALID_EMAIL")

        msg = messages_by_key.get(company_key)
        if not msg:
            error_parts.append("MESSAGE_NOT_FOUND")

        subject = msg["subject"] if msg else ""
        body_text = msg["body_text"] if msg else ""

        if msg and not subject.strip():
            error_parts.append("EMPTY_SUBJECT")
        if msg and not body_text.strip():
            error_parts.append("EMPTY_BODY")

        if error_parts:
            status = "ERROR"
            error_message = ", ".join(error_parts)
            stats["error"] += 1
        else:
            status = "READY"
            error_message = ""
            stats["ready"] += 1

        db.insert_outbox(
            conn,
            company=company,
            company_key=company_key,
            email=email if email else "",
            firstname=firstname,
            lastname=lastname,
            subject=subject,
            body_text=body_text,
            status=status,
            error_message=error_message,
        )

        if email:
            seen_emails.add(email)

        stats["details"].append({
            "company": company, "email": email,
            "status": status, "reason": error_message
        })

    conn.commit()
    logger.info("Outbox built: %d READY, %d ERROR, %d duplicates skipped",
                stats["ready"], stats["error"], stats["skipped_duplicates"])
    return stats
