"""
Bounce tracker: connect to IMAP, detect DSN/bounces,
extract recipient + diagnostic, update outbox status.
Tracks already-processed bounces via seen_bounces.json (by UID).
"""

import imaplib
import email
import json
import os
import re
import logging
from datetime import datetime, timedelta
from email import policy

from dotenv import load_dotenv

from engine import db

load_dotenv()
logger = logging.getLogger("b2b.bounce_tracker")

SEEN_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "seen_bounces.json")

# Patterns to identify bounce messages
BOUNCE_FROM_RE = re.compile(r"mailer-daemon|postmaster", re.IGNORECASE)
BOUNCE_SUBJECT_RE = re.compile(
    r"undelivered|delivery status|failure notice|returned mail|non remis|"
    r"mail delivery failed|undeliverable",
    re.IGNORECASE,
)
RECIPIENT_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
DIAG_CODE_RE = re.compile(r"(\d\.\d\.\d)")


def _load_seen() -> set:
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_seen(seen: set):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def _get_imap_config() -> dict:
    return {
        "host": os.getenv("IMAP_HOST", "imap.gmail.com"),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "user": os.getenv("IMAP_USER", os.getenv("SMTP_USER", "")),
        "password": os.getenv("IMAP_PASSWORD", os.getenv("SMTP_APP_PASSWORD", "")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
    }


def test_imap_connection() -> tuple[bool, str]:
    """Test IMAP connection. Returns (success, message)."""
    cfg = _get_imap_config()
    if not cfg["user"] or not cfg["password"]:
        return False, "IMAP_USER ou IMAP_PASSWORD non configure."
    try:
        mail = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        mail.login(cfg["user"], cfg["password"])
        mail.select(cfg["folder"], readonly=True)
        mail.logout()
        return True, f"Connexion IMAP OK ({cfg['host']}:{cfg['port']} as {cfg['user']})"
    except imaplib.IMAP4.error as e:
        return False, f"Erreur IMAP: {e}"
    except Exception as e:
        return False, f"Erreur: {e}"


def _is_bounce(msg: email.message.Message) -> bool:
    """Check if a message is a bounce/DSN."""
    from_addr = str(msg.get("From", ""))
    subject = str(msg.get("Subject", ""))
    content_type = str(msg.get("Content-Type", ""))

    if BOUNCE_FROM_RE.search(from_addr):
        return True
    if BOUNCE_SUBJECT_RE.search(subject):
        return True
    if "delivery-status" in content_type.lower():
        return True
    return False


def _extract_bounce_info(msg: email.message.Message) -> tuple[str | None, str, str]:
    """
    Extract bounce information from a message.
    Returns (recipient_email, diagnostic_code, raw_diagnostic).
    """
    recipient = None
    diag_code = ""
    raw_diag = ""

    # Walk all parts
    body_text = ""
    for part in msg.walk():
        ct = part.get_content_type()

        # DSN delivery-status part
        if ct == "message/delivery-status":
            payload = part.get_payload()
            if isinstance(payload, list):
                for sub in payload:
                    text = str(sub)
                    # Look for Final-Recipient or Original-Recipient
                    for line in text.splitlines():
                        lower = line.lower().strip()
                        if lower.startswith("final-recipient:") or lower.startswith("original-recipient:"):
                            match = RECIPIENT_RE.search(line)
                            if match:
                                recipient = match.group(0).lower()
                        if lower.startswith("diagnostic-code:"):
                            raw_diag = line.split(":", 1)[-1].strip()
                            code_match = DIAG_CODE_RE.search(raw_diag)
                            if code_match:
                                diag_code = code_match.group(1)
            elif isinstance(payload, str):
                for line in payload.splitlines():
                    lower = line.lower().strip()
                    if lower.startswith("final-recipient:") or lower.startswith("original-recipient:"):
                        match = RECIPIENT_RE.search(line)
                        if match:
                            recipient = match.group(0).lower()
                    if lower.startswith("diagnostic-code:"):
                        raw_diag = line.split(":", 1)[-1].strip()
                        code_match = DIAG_CODE_RE.search(raw_diag)
                        if code_match:
                            diag_code = code_match.group(1)

        # Plain text body -- fallback for recipient extraction
        elif ct == "text/plain":
            try:
                text = part.get_payload(decode=True)
                if text:
                    body_text += text.decode("utf-8", errors="replace")
            except Exception:
                pass

    # Fallback: search in body text
    if not recipient and body_text:
        emails_found = RECIPIENT_RE.findall(body_text)
        # Filter out mailer-daemon-like addresses
        for e in emails_found:
            e_lower = e.lower()
            if "mailer-daemon" not in e_lower and "postmaster" not in e_lower:
                recipient = e_lower
                break
        if not diag_code:
            code_match = DIAG_CODE_RE.search(body_text)
            if code_match:
                diag_code = code_match.group(1)

    return recipient, diag_code, raw_diag


def check_bounces(since_days: int = 7, progress_callback=None) -> dict:
    """
    Check IMAP for bounce messages and update outbox.

    Args:
        since_days: look at messages from the last N days
        progress_callback: optional callable(current, total, email, status)

    Returns dict: {bounced, invalid, already_seen, errors, details}
    """
    cfg = _get_imap_config()
    stats = {
        "bounced": 0,
        "invalid": 0,
        "already_seen": 0,
        "processed": 0,
        "details": [],
    }

    if not cfg["user"] or not cfg["password"]:
        stats["error"] = "IMAP credentials not configured."
        return stats

    seen = _load_seen()

    try:
        mail = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        mail.login(cfg["user"], cfg["password"])
        mail.select(cfg["folder"], readonly=True)
    except Exception as e:
        stats["error"] = f"IMAP connection failed: {e}"
        logger.error("IMAP connection failed: %s", e)
        return stats

    # Search for recent messages
    since_date = (datetime.utcnow() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    try:
        status_code, data = mail.search(None, f'(SINCE {since_date})')
        if status_code != "OK":
            mail.logout()
            stats["error"] = "IMAP search failed."
            return stats
    except Exception as e:
        mail.logout()
        stats["error"] = f"IMAP search error: {e}"
        return stats

    msg_ids = data[0].split() if data[0] else []
    logger.info("Found %d messages since %s", len(msg_ids), since_date)

    conn = db.get_connection()

    for i, msg_id in enumerate(msg_ids):
        uid_str = msg_id.decode("utf-8", errors="replace")

        if uid_str in seen:
            stats["already_seen"] += 1
            continue

        try:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw, policy=policy.default)
        except Exception as e:
            logger.debug("Failed to fetch message %s: %s", uid_str, e)
            continue

        if not _is_bounce(msg):
            seen.add(uid_str)
            continue

        recipient, diag_code, raw_diag = _extract_bounce_info(msg)

        if not recipient:
            logger.debug("Bounce detected but no recipient found (msg %s)", uid_str)
            seen.add(uid_str)
            continue

        # Determine status
        if diag_code == "5.1.1":
            new_status = "INVALID"
            stats["invalid"] += 1
        else:
            new_status = "BOUNCED"
            stats["bounced"] += 1

        # Update outbox
        db.update_outbox_status_by_email(
            conn, recipient, new_status,
            error_message=f"diag={diag_code} {raw_diag}".strip()
        )
        conn.commit()

        stats["processed"] += 1
        stats["details"].append({
            "email": recipient,
            "status": new_status,
            "diag_code": diag_code,
            "raw_diag": raw_diag,
        })

        if progress_callback:
            progress_callback(i + 1, len(msg_ids), recipient, new_status)

        seen.add(uid_str)

    _save_seen(seen)

    try:
        mail.logout()
    except Exception:
        pass

    conn.close()
    logger.info("Bounce check done: %d bounced, %d invalid, %d already seen",
                stats["bounced"], stats["invalid"], stats["already_seen"])
    return stats
