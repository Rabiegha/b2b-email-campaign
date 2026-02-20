"""
Page 5 -- Track Bounces
Check IMAP for bounce messages (DSN) and update outbox status.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.bounce_tracker import check_bounces
from engine.io_utils import rows_to_dataframe

st.set_page_config(page_title="Track Bounces", layout="wide")
st.title("5 -- Track Bounces")

st.markdown(
    """
Verifie les messages de bounce (Delivery Status Notification) via IMAP.

- Identifie les messages de **mailer-daemon** ou avec un sujet DSN.
- Extrait l'adresse destinataire et le code diagnostic.
- Si code **5.1.1** -> statut **INVALID** (adresse inexistante).
- Sinon -> statut **BOUNCED**.
- Les bounces deja traites sont ignores (seen_bounces.json).
"""
)

since_days = st.number_input("Verifier les messages des N derniers jours", min_value=1, max_value=90, value=7)

if st.button("Verifier les bounces"):
    progress_bar = st.progress(0, text="Connexion IMAP...")
    log_area = st.empty()
    bounce_log: list[dict] = []

    def on_progress(current, total, email_addr, status):
        pct = current / total if total > 0 else 1.0
        progress_bar.progress(pct, text=f"Analyse {current}/{total}")
        if email_addr:
            bounce_log.append({"email": email_addr, "status": status})
            log_area.dataframe(pd.DataFrame(bounce_log), use_container_width=True)

    stats = check_bounces(since_days=since_days, progress_callback=on_progress)

    progress_bar.progress(1.0, text="Termine !")

    if stats.get("error"):
        st.error(stats["error"])
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("BOUNCED", stats["bounced"])
        c2.metric("INVALID", stats["invalid"])
        c3.metric("Deja traites (ignores)", stats["already_seen"])

    if stats["details"]:
        st.markdown("### Details des bounces detectes")
        st.dataframe(pd.DataFrame(stats["details"]), use_container_width=True)

st.markdown("---")

# Show bounced / invalid entries
st.header("Emails bounced/invalid dans l'outbox")
try:
    conn = db.get_connection()
    bounced = conn.execute(
        "SELECT * FROM outbox WHERE status IN ('BOUNCED','INVALID') ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()

    if bounced:
        df = rows_to_dataframe(bounced)
        display_cols = ["id", "email", "company", "status", "error_message", "updated_at"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], use_container_width=True)
        st.metric("Total bounced/invalid", len(df))
    else:
        st.info("Aucun bounce detecte pour le moment.")
except Exception as e:
    st.error(str(e))
