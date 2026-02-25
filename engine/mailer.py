"""
Mailer: send emails via SMTP (Gmail / Google Workspace).
Uses TLS on port 587 with App Password authentication.
Handles quotas, random delays, and error capture.
"""

import smtplib
import time
import random
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from dotenv import load_dotenv

from engine import db

load_dotenv()
logger = logging.getLogger("b2b.mailer")


def _get_smtp_config() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_APP_PASSWORD", ""),
    }


def _get_send_config() -> dict:
    return {
        "min_delay": float(os.getenv("SEND_MIN_DELAY", "5")),
        "max_delay": float(os.getenv("SEND_MAX_DELAY", "15")),
        "max_per_run": int(os.getenv("SEND_MAX_PER_RUN", "50")),
    }


def test_smtp_connection() -> tuple[bool, str]:
    """
    Test SMTP connection with current credentials.
    Returns (success: bool, message: str).
    """
    cfg = _get_smtp_config()
    if not cfg["user"] or not cfg["password"]:
        return False, "SMTP_USER ou SMTP_APP_PASSWORD non configure."
    try:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["user"], cfg["password"])
        server.quit()
        return True, f"Connexion SMTP OK ({cfg['host']}:{cfg['port']} as {cfg['user']})"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Erreur authentification: {e}"
    except Exception as e:
        return False, f"Erreur SMTP: {e}"


def _send_single_email(server: smtplib.SMTP, from_addr: str,
                       to_addr: str, subject: str, body_text: str,
                       firstname: str = "", lastname: str = "") -> tuple[bool, str]:
    """
    Send a single email. Returns (success, error_message).
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject

        # Plain text
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        server.sendmail(from_addr, [to_addr], msg.as_string())
        logger.info("Email sent to %s", to_addr)
        return True, ""
    except smtplib.SMTPRecipientsRefused as e:
        err = f"Recipient refused: {e}"
        logger.warning(err)
        return False, err
    except smtplib.SMTPException as e:
        err = f"SMTP error: {e}"
        logger.warning(err)
        return False, err
    except Exception as e:
        err = f"Unexpected error: {e}"
        logger.error(err)
        return False, err


def send_ready_emails(progress_callback=None,
                      max_emails: int | None = None,
                      min_delay: float | None = None,
                      max_delay: float | None = None,
                      stop_flag=None,
                      outbox_ids: list[int] | None = None) -> dict:
    """
    Send READY emails from the outbox.

    Args:
        progress_callback: optional callable(current, total, email, status, delay)
        max_emails: override for SEND_MAX_PER_RUN (None = use env)
        min_delay: override for SEND_MIN_DELAY (None = use env)
        max_delay: override for SEND_MAX_DELAY (None = use env)
        stop_flag: threading.Event – if set, stop the loop gracefully
        outbox_ids: if provided, only send these specific outbox IDs

    Returns dict with stats: {sent, errors, skipped, total, details, error, elapsed}
    """
    import time as _time
    t_start = _time.monotonic()

    cfg = _get_smtp_config()
    send_cfg = _get_send_config()

    # Allow caller overrides
    eff_min_delay = min_delay if min_delay is not None else send_cfg["min_delay"]
    eff_max_delay = max_delay if max_delay is not None else send_cfg["max_delay"]
    eff_max = max_emails if max_emails is not None else send_cfg["max_per_run"]

    if not cfg["user"] or not cfg["password"]:
        return {"sent": 0, "errors": 0, "skipped": 0, "total": 0,
                "details": [], "error": "SMTP credentials not configured.",
                "elapsed": 0}

    conn = db.get_connection()

    if outbox_ids is not None:
        # Send only the specified IDs
        id_set = set(outbox_ids)
        all_ready = db.get_outbox(conn, status_filter="READY")
        rows_to_send = [r for r in all_ready if r["id"] in id_set]
    else:
        ready_rows = db.get_outbox(conn, status_filter="READY")
        rows_to_send = ready_rows[:eff_max]

    max_to_send = len(rows_to_send)

    stats = {"sent": 0, "errors": 0, "skipped": 0,
             "total": max_to_send, "details": [], "elapsed": 0}

    if not rows_to_send:
        conn.close()
        return stats

    try:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["user"], cfg["password"])
    except Exception as e:
        conn.close()
        stats["error"] = f"SMTP connection failed: {e}"
        stats["elapsed"] = round(_time.monotonic() - t_start, 1)
        logger.error("SMTP connection failed: %s", e)
        return stats

    for i, row in enumerate(rows_to_send):
        # Check stop flag
        if stop_flag and stop_flag.is_set():
            stats["skipped"] = max_to_send - i
            break

        outbox_id = row["id"]
        to_addr = row["email"]
        subject = row["subject"]
        body_text = row["body_text"]
        firstname = row["firstname"] or ""
        lastname = row["lastname"] or ""

        success, err = _send_single_email(
            server, cfg["user"], to_addr, subject, body_text, firstname, lastname
        )

        now = datetime.utcnow().isoformat()

        if success:
            db.update_outbox_status(conn, outbox_id, "SENT", sent_at=now)
            stats["sent"] += 1
            detail_status = "SENT"
        else:
            db.update_outbox_status(conn, outbox_id, "ERROR", error_message=err)
            stats["errors"] += 1
            detail_status = "ERROR"

        conn.commit()

        # Compute next delay
        next_delay = 0.0
        if i < len(rows_to_send) - 1:
            next_delay = round(random.uniform(eff_min_delay, eff_max_delay), 1)

        stats["details"].append({
            "email": to_addr,
            "company": row.get("company", ""),
            "subject": subject,
            "status": detail_status,
            "error": err,
            "time": now,
        })

        if progress_callback:
            progress_callback(i + 1, max_to_send, to_addr, detail_status, next_delay)

        # Random delay between sends (except after last)
        if next_delay > 0:
            logger.debug("Waiting %.1fs before next send...", next_delay)
            # Sleep in small increments so stop_flag can interrupt
            waited = 0.0
            while waited < next_delay:
                if stop_flag and stop_flag.is_set():
                    break
                time.sleep(min(0.5, next_delay - waited))
                waited += 0.5

    try:
        server.quit()
    except Exception:
        pass

    conn.close()
    stats["elapsed"] = round(_time.monotonic() - t_start, 1)
    logger.info("Send run complete: %d sent, %d errors out of %d (%.1fs)",
                stats["sent"], stats["errors"], max_to_send, stats["elapsed"])
    return stats
