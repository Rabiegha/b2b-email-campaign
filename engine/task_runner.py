"""
Background task runner for long-running operations.
Uses threading + a JSON progress file so any Streamlit page can display status.
"""

import json
import os
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger("b2b.task_runner")

PROGRESS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "task_progress.json")


def _default_progress() -> dict:
    return {
        "running": False,
        "task_name": "",
        "current": 0,
        "total": 0,
        "message": "",
        "started_at": "",
        "finished_at": "",
        "error": "",
        "results": {},
    }


def read_progress() -> dict:
    """Read current task progress from disk. Safe to call from any page."""
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_progress()


def _write_progress(data: dict):
    """Write progress to disk (called from the background thread)."""
    os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_running() -> bool:
    return read_progress().get("running", False)


def clear_progress():
    """Reset the progress file."""
    _write_progress(_default_progress())


def run_email_search(max_prospects: int = 0, force_refresh: bool = False):
    """
    Run the email search in a background thread.
    Progress is written to PROGRESS_PATH so any page can read it.
    """
    if is_running():
        logger.warning("A task is already running, ignoring new request.")
        return False

    thread = threading.Thread(
        target=_email_search_worker,
        args=(max_prospects, force_refresh),
        daemon=True,
    )
    thread.start()
    return True


def _email_search_worker(max_prospects: int, force_refresh: bool):
    """The actual worker that runs in a background thread."""
    from engine import db
    from engine.domain_finder import find_domain
    from engine.web_discovery import discover_emails
    from engine.email_pattern import infer_pattern, generate_email
    from engine.email_verifier import find_best_email, hunter_domain_search

    progress = _default_progress()
    progress["running"] = True
    progress["task_name"] = "Recherche d'emails"
    progress["started_at"] = datetime.utcnow().isoformat()
    progress["message"] = "Démarrage..."
    _write_progress(progress)

    try:
        conn = db.get_connection()

        if max_prospects > 0:
            if force_refresh:
                prospects = db.get_all_prospects_for_find(conn, limit=max_prospects)
            else:
                prospects = db.get_prospects_without_suggestion(conn, limit=max_prospects)
        else:
            if force_refresh:
                prospects = db.get_all_prospects_for_find(conn)
            else:
                prospects = db.get_prospects_without_suggestion(conn)

        total = len(prospects)
        progress["total"] = total

        if total == 0:
            progress["message"] = "Aucun prospect à traiter."
            progress["running"] = False
            progress["finished_at"] = datetime.utcnow().isoformat()
            _write_progress(progress)
            conn.close()
            return

        # Group by company_key
        company_groups: dict[str, list] = {}
        for p in prospects:
            ck = p["company_key"]
            if ck not in company_groups:
                company_groups[ck] = []
            company_groups[ck].append(p)

        processed = 0
        found_count = 0
        not_found_count = 0

        for ck, group in company_groups.items():
            company = group[0]["company"]
            progress["current"] = processed
            progress["message"] = f"Traitement : {company}"
            _write_progress(progress)

            # 1) Find domain
            domain = find_domain(company, force_refresh=force_refresh)

            if not domain:
                for p in group:
                    db.upsert_email_suggestion(
                        conn, p["id"], None, None, None, 0.0,
                        "NOT_FOUND", "Domaine non trouvé"
                    )
                    processed += 1
                    not_found_count += 1
                conn.commit()
                progress["current"] = processed
                _write_progress(progress)
                continue

            # 2) Try Hunter.io first for domain-level pattern (one call per domain)
            hunter_result = hunter_domain_search(domain)
            known_pattern = hunter_result["pattern"] if hunter_result else None

            # 3) Also discover emails via web crawl for extra signal
            found_emails = discover_emails(domain)

            # 4) Infer pattern from discovered emails (enriched with names)
            known_names = [
                (p["firstname"], p["lastname"])
                for p in group
                if p.get("firstname") and p.get("lastname")
            ]
            inferred_pattern, inferred_conf, infer_debug = infer_pattern(
                domain, found_emails,
                known_names=known_names,
                force_refresh=force_refresh
            )

            # Choose the best pattern source
            if hunter_result:
                base_pattern = known_pattern
                base_source = "hunter"
            else:
                base_pattern = inferred_pattern
                base_source = "inferred"

            # 5) For each prospect: generate + SMTP verify
            for p in group:
                progress["message"] = f"Vérification : {p['firstname']} {p['lastname']} @ {company}"
                _write_progress(progress)

                email, pattern, confidence, debug = find_best_email(
                    p["firstname"], p["lastname"], domain,
                    known_pattern=base_pattern,
                    skip_smtp=False,
                )

                # Enrich debug info
                notes = f"domain={domain}, source={base_source}, {debug}"
                if found_emails:
                    notes += f", web_emails={len(found_emails)}"

                status = "FOUND" if email else "NOT_FOUND"

                db.upsert_email_suggestion(
                    conn, p["id"], domain, pattern, email,
                    confidence, status, notes
                )
                processed += 1
                if status == "FOUND":
                    found_count += 1
                else:
                    not_found_count += 1

            conn.commit()
            progress["current"] = processed
            _write_progress(progress)

        conn.close()

        progress["running"] = False
        progress["current"] = total
        progress["finished_at"] = datetime.utcnow().isoformat()
        progress["message"] = f"Terminé : {total} prospects traités"
        progress["results"] = {
            "total": total,
            "found": found_count,
            "not_found": not_found_count,
        }
        _write_progress(progress)
        logger.info("Email search completed: %d total, %d found, %d not found",
                     total, found_count, not_found_count)

    except Exception as e:
        logger.error("Email search failed: %s", e, exc_info=True)
        progress["running"] = False
        progress["error"] = str(e)
        progress["finished_at"] = datetime.utcnow().isoformat()
        progress["message"] = f"Erreur : {e}"
        _write_progress(progress)
