"""
Page 5 -- Suivi Bounces
Vérification des bounces via IMAP et mise à jour de l'outbox.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.bounce_tracker import check_bounces
from engine.io_utils import rows_to_dataframe

st.set_page_config(page_title="Suivi Bounces", page_icon="📊", layout="wide")
st.title("5 — 📊 Suivi Bounces")

st.markdown(
    "Vérifie votre boîte mail pour détecter les **retours d'erreur** (bounces). "
    "Les adresses invalides seront automatiquement marquées."
)

# ── IMAP check ──────────────────────────────────────────
from dotenv import load_dotenv
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)
imap_configured = bool(os.getenv("IMAP_HOST")) and bool(os.getenv("IMAP_USER", os.getenv("SMTP_USER")))

if not imap_configured:
    st.warning(
        "⚠️ **IMAP non configuré !** Allez dans **⚙️ Réglages** pour entrer "
        "vos identifiants IMAP."
    )

st.markdown("---")

since_days = st.number_input(
    "📅 Vérifier les messages des N derniers jours",
    min_value=1, max_value=90, value=7,
)

if st.button("🔍 Vérifier les bounces", type="primary", width="stretch"):
    progress_bar = st.progress(0, text="Connexion IMAP…")
    log_area = st.empty()
    bounce_log: list[dict] = []

    def on_progress(current, total, email_addr, status):
        pct = current / total if total > 0 else 1.0
        progress_bar.progress(pct, text=f"Analyse {current}/{total}")
        if email_addr:
            label = "❌ Invalide" if status == "INVALID" else "↩️ Bounce"
            bounce_log.append({"email": email_addr, "statut": label})
            log_area.dataframe(pd.DataFrame(bounce_log), width="stretch")

    stats = check_bounces(since_days=since_days, progress_callback=on_progress)

    progress_bar.progress(1.0, text="✅ Terminé !")

    if stats.get("error"):
        st.error(f"Erreur : {stats['error']}")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("↩️ Bounces", stats["bounced"])
        c2.metric("❌ Invalides", stats["invalid"])
        c3.metric("🔄 Déjà traités", stats["already_seen"])

    if stats.get("details"):
        with st.expander("📋 Détail des bounces détectés"):
            st.dataframe(pd.DataFrame(stats["details"]), width="stretch")

st.markdown("---")

# ── Show bounced / invalid entries ──────────────────────
st.subheader("📋 Adresses en erreur dans l'outbox")
try:
    conn = db.get_connection()
    bounced = conn.execute(
        "SELECT * FROM outbox WHERE status IN ('BOUNCED','INVALID') ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()

    if bounced:
        df = rows_to_dataframe(bounced)
        STATUS_LABELS = {"BOUNCED": "↩️ Bounce", "INVALID": "❌ Invalide"}
        df["statut"] = df["status"].map(STATUS_LABELS).fillna(df["status"])

        display_cols = ["statut", "email", "company", "error_message", "updated_at"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], width="stretch", hide_index=True)
        st.metric("Total en erreur", len(df))
    else:
        st.markdown(
            """
            <div style="text-align:center; padding:2rem 1rem;">
                <div style="font-size:2.5rem;">🎉</div>
                <p style="color:#888;">Aucun bounce détecté — tout va bien !</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
except Exception as e:
    st.error(str(e))
    st.error(str(e))
