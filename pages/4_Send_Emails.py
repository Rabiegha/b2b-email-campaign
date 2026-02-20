"""
Page 4 -- Send Emails
Send READY emails from the outbox via SMTP.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.mailer import send_ready_emails
from engine.io_utils import rows_to_dataframe

st.set_page_config(page_title="Send Emails", layout="wide")
st.title("4 -- Send Emails")

st.markdown(
    """
Envoie les emails avec le statut **READY** de l'outbox via SMTP.

- Delai aleatoire entre chaque envoi (configurable dans Settings).
- Nombre maximum par run (configurable dans Settings).
- Les statuts sont mis a jour : SENT ou ERROR.
"""
)

# Show current ready count
try:
    conn = db.get_connection()
    outbox_stats = db.count_outbox_by_status(conn)
    conn.close()
    ready_count = outbox_stats.get("READY", 0)
    st.metric("Emails READY a envoyer", ready_count)
except Exception:
    ready_count = 0

if ready_count == 0:
    st.info("Aucun email READY dans l'outbox.")
else:
    min_d = os.getenv("SEND_MIN_DELAY", "5")
    max_d = os.getenv("SEND_MAX_DELAY", "15")
    max_r = os.getenv("SEND_MAX_PER_RUN", "50")
    st.markdown(f"**Config :** delai {min_d}-{max_d}s, max {max_r}/run")

    if st.button("Envoyer les emails READY"):
        progress_bar = st.progress(0, text="Envoi en cours...")
        log_area = st.empty()
        send_log: list[dict] = []

        def on_progress(current, total, email_addr, status):
            progress_bar.progress(current / total, text=f"{current}/{total} -- {email_addr} : {status}")
            send_log.append({"email": email_addr, "status": status})
            log_area.dataframe(pd.DataFrame(send_log), use_container_width=True)

        stats = send_ready_emails(progress_callback=on_progress)

        progress_bar.progress(1.0, text="Termine !")

        c1, c2, c3 = st.columns(3)
        c1.metric("Envoyes", stats["sent"])
        c2.metric("Erreurs", stats["errors"])
        c3.metric("Total traites", stats["total"])

        if stats.get("error"):
            st.error(stats["error"])

        if stats["details"]:
            st.dataframe(pd.DataFrame(stats["details"]), use_container_width=True)

st.markdown("---")

# Recent sends
st.header("Derniers envois")
try:
    conn = db.get_connection()
    sent_rows = conn.execute(
        "SELECT * FROM outbox WHERE status='SENT' ORDER BY sent_at DESC LIMIT 50"
    ).fetchall()
    conn.close()

    if sent_rows:
        df = rows_to_dataframe(sent_rows)
        display_cols = ["id", "email", "company", "subject", "status", "sent_at"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], use_container_width=True)
    else:
        st.info("Aucun email envoye pour le moment.")
except Exception as e:
    st.error(str(e))
