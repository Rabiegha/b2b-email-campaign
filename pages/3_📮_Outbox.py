"""
Page 3 -- Outbox
Build the outbox (merge emails + messages), view, filter, and export.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.outbox import build_outbox
from engine.io_utils import rows_to_dataframe, df_to_csv_bytes

st.set_page_config(page_title="Outbox", layout="wide")
st.title("3 — 📮 Outbox")

STATUS_LABELS = {
    "READY": "📬 Prêt",
    "SENT": "✅ Envoyé",
    "ERROR": "⚠️ Erreur",
    "BOUNCED": "↩️ Bounce",
    "INVALID": "❌ Invalide",
}

# ── Quick stats row ────────────────────────────────────
try:
    conn = db.get_connection()
    outbox_stats = db.count_outbox_by_status(conn)
    total_outbox = sum(outbox_stats.values()) if outbox_stats else 0
    conn.close()
except Exception:
    outbox_stats = {}
    total_outbox = 0

if total_outbox > 0:
    stat_cols = st.columns(len(outbox_stats) + 1)
    stat_cols[0].metric("📊 Total", total_outbox)
    for i, (status, count) in enumerate(sorted(outbox_stats.items())):
        label = STATUS_LABELS.get(status, status)
        stat_cols[i + 1].metric(label, count)
    st.markdown("")

# ── Build outbox section ─────────────────────────────
with st.expander("🔨 Construire / reconstruire l'outbox", expanded=(total_outbox == 0)):
    st.markdown(
        "Associe chaque prospect (avec email trouvé) au message correspondant "
        "par entreprise. Un email est **Prêt** si l'adresse, le sujet et le corps "
        "sont tous présents."
    )

    if st.button("🚀 Construire l'outbox", type="primary", width="stretch"):
        with st.spinner("Construction en cours…"):
            conn = db.get_connection()
            stats = build_outbox(conn)
            conn.close()

        c1, c2, c3 = st.columns(3)
        c1.metric("📬 Prêts", stats["ready"])
        c2.metric("⚠️ Erreurs", stats["error"])
        c3.metric("🔄 Doublons ignorés", stats["skipped_duplicates"])

        if stats["details"]:
            with st.expander("📋 Détail des erreurs"):
                df_details = pd.DataFrame(stats["details"])
                st.dataframe(df_details, width="stretch", height=250)

        st.success("✅ Outbox construit ! Vérifiez le tableau ci-dessous.")
        st.rerun()

st.markdown("---")

# ── Outbox table with filters ─────────────────────────
st.subheader("📋 Tableau de l'outbox")

col_filter, col_search = st.columns([1, 2])
with col_filter:
    status_options = ["Tous"] + list(STATUS_LABELS.keys())
    status_filter = st.selectbox(
        "Filtrer par statut",
        status_options,
        format_func=lambda x: STATUS_LABELS.get(x, "🔎 Tous"),
        key="outbox_status_filter",
    )
with col_search:
    search_text = st.text_input(
        "🔍 Rechercher",
        placeholder="Entreprise, email, sujet…",
        key="outbox_search",
    )

try:
    conn = db.get_connection()
    sf = status_filter if status_filter != "Tous" else None
    st_text = search_text.strip() if search_text.strip() else None
    rows = db.get_outbox(conn, status_filter=sf, search_text=st_text)
    conn.close()

    if rows:
        df = rows_to_dataframe(rows)

        # Human-readable status
        df["statut"] = df["status"].map(STATUS_LABELS).fillna(df["status"])

        display_cols = ["statut", "company", "email", "firstname", "lastname",
                        "subject", "error_message", "sent_at"]
        available = [c for c in display_cols if c in df.columns]

        st.caption(f"{len(df)} ligne(s)")
        st.dataframe(
            df[available],
            width="stretch",
            height=500,
            hide_index=True,
            column_config={
                "statut": st.column_config.TextColumn("Statut", width="small"),
                "sent_at": st.column_config.TextColumn("Envoyé le"),
                "error_message": st.column_config.TextColumn("Détail erreur", width="medium"),
            },
        )

        # Export
        csv_bytes = df_to_csv_bytes(df)
        st.download_button(
            label="📥 Exporter en CSV",
            data=csv_bytes,
            file_name="outbox_export.csv",
            mime="text/csv",
            width="stretch",
        )

        # Next step CTA
        n_ready = outbox_stats.get("READY", 0)
        if n_ready > 0:
            st.markdown("---")
            st.info(
                f"**👉 Prochaine étape :** Vous avez **{n_ready}** email(s) prêts à envoyer. "
                f"Allez sur la page **✉️ Envoi** pour les expédier."
            )

    else:
        if total_outbox == 0:
            st.markdown(
                """
                <div style="text-align:center; padding:3rem 1rem;">
                    <div style="font-size:3rem;">📮</div>
                    <h3>Votre outbox est vide</h3>
                    <p style="color:#888;">
                        Cliquez sur <strong>Construire l'outbox</strong> ci-dessus pour
                        associer vos prospects à leurs messages.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info("Aucune ligne ne correspond aux filtres sélectionnés.")

except Exception as e:
    st.error(str(e))

