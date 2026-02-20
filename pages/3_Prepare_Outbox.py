"""
Page 3 -- Prepare Outbox
Merge email suggestions with messages to build the outbox.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.outbox import build_outbox
from engine.io_utils import rows_to_dataframe, df_to_csv_bytes

st.set_page_config(page_title="Prepare Outbox", layout="wide")
st.title("3 -- Prepare Outbox")

st.markdown(
    """
Cette etape fusionne les suggestions d'emails avec les messages via la cle entreprise normalisee.

**Regles :**
- Un email est marque **READY** si : email valide + subject + body_text presents.
- Sinon **ERROR** avec la raison (EMAIL_NOT_FOUND, MESSAGE_NOT_FOUND, INVALID_EMAIL, etc.).
- Les emails en doublon sont ignores (le premier est garde).
"""
)

if st.button("Construire l'outbox"):
    with st.spinner("Construction de l'outbox en cours..."):
        conn = db.get_connection()
        stats = build_outbox(conn)
        conn.close()

    st.success("Outbox construit.")

    c1, c2, c3 = st.columns(3)
    c1.metric("READY", stats["ready"])
    c2.metric("ERROR", stats["error"])
    c3.metric("Doublons ignores", stats["skipped_duplicates"])

    if stats["details"]:
        df_details = pd.DataFrame(stats["details"])
        st.dataframe(df_details, use_container_width=True, height=300)

st.markdown("---")

# Show outbox
st.header("Apercu de l'outbox")
try:
    conn = db.get_connection()
    outbox_rows = db.get_outbox(conn)
    outbox_stats = db.count_outbox_by_status(conn)
    conn.close()

    if outbox_stats:
        cols = st.columns(len(outbox_stats))
        for i, (status, count) in enumerate(sorted(outbox_stats.items())):
            cols[i].metric(status, count)

    if outbox_rows:
        df = rows_to_dataframe(outbox_rows)
        display_cols = ["id", "company", "email", "firstname", "lastname",
                        "subject", "status", "error_message", "sent_at"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], use_container_width=True, height=500)

        # Export button
        csv_bytes = df_to_csv_bytes(df)
        st.download_button(
            label="Exporter outbox.csv",
            data=csv_bytes,
            file_name="outbox.csv",
            mime="text/csv",
        )
    else:
        st.info("L'outbox est vide. Lancez d'abord 'Construire l'outbox'.")
except Exception as e:
    st.error(str(e))
