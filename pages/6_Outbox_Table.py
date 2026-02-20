"""
Page 6 -- Outbox Table
Full view of the outbox with filters and CSV export.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.io_utils import rows_to_dataframe, df_to_csv_bytes

st.set_page_config(page_title="Outbox Table", layout="wide")
st.title("6 -- Outbox Table")

# Filters
col1, col2 = st.columns(2)
with col1:
    status_options = ["Tous", "READY", "SENT", "ERROR", "BOUNCED", "INVALID"]
    status_filter = st.selectbox("Filtrer par statut", status_options)
with col2:
    search_text = st.text_input("Recherche (company, email, subject)")

# Query
try:
    conn = db.get_connection()
    sf = status_filter if status_filter != "Tous" else None
    st_text = search_text.strip() if search_text.strip() else None
    rows = db.get_outbox(conn, status_filter=sf, search_text=st_text)
    outbox_stats = db.count_outbox_by_status(conn)
    conn.close()

    # Stats row
    if outbox_stats:
        stat_cols = st.columns(len(outbox_stats) + 1)
        total = sum(outbox_stats.values())
        stat_cols[0].metric("Total", total)
        for i, (status, count) in enumerate(sorted(outbox_stats.items())):
            stat_cols[i + 1].metric(status, count)

    if rows:
        df = rows_to_dataframe(rows)
        display_cols = ["id", "company", "email", "firstname", "lastname",
                        "subject", "body_text", "status", "error_message",
                        "sent_at", "updated_at"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], use_container_width=True, height=600)

        # Export
        csv_bytes = df_to_csv_bytes(df[available])
        st.download_button(
            label="Exporter en CSV",
            data=csv_bytes,
            file_name="outbox_export.csv",
            mime="text/csv",
        )
    else:
        st.info("Aucune ligne dans l'outbox correspondant aux filtres.")

except Exception as e:
    st.error(str(e))
