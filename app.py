"""
B2B Email Campaign -- Streamlit Application
Main entry point. Configures logging, initializes DB, sets up sidebar.
"""

import os
import sys
import logging
import streamlit as st

# -- Ensure project root is on path --
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine import db
from engine.task_runner import read_progress

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("b2b.app")

# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------
db.init_db()

# ---------------------------------------------------------------------------
# Streamlit page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="B2B Email Campaign",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for a polished look
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* ── Global ─────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
}
[data-testid="stSidebar"] * {
    color: #e0e0e0 !important;
}
[data-testid="stSidebar"] .stButton > button {
    color: #fff !important;
    border-color: rgba(255,255,255,0.2);
}

/* ── Step cards ─────────────────────────────────────── */
.step-card {
    background: #ffffff;
    border: 1px solid #e0e4e8;
    border-radius: 12px;
    padding: 1.2rem;
    text-align: center;
    transition: box-shadow 0.2s, transform 0.15s;
    height: 100%;
}
.step-card:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.10);
    transform: translateY(-2px);
}

/* ── Metric cards ───────────────────────────────────── */
[data-testid="stMetric"] {
    background: #f8f9fa;
    border-radius: 10px;
    padding: 0.8rem;
    border: 1px solid #e9ecef;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar – Mini dashboard
# ---------------------------------------------------------------------------
st.sidebar.markdown("## 📧 B2B Campaign")
st.sidebar.markdown("---")

# Gather stats for sidebar
try:
    conn = db.get_connection()
    n_prospects = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    n_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    n_suggestions = conn.execute("SELECT COUNT(*) FROM email_suggestions").fetchone()[0]
    n_found = conn.execute("SELECT COUNT(*) FROM email_suggestions WHERE status='FOUND'").fetchone()[0]
    n_manual = conn.execute("SELECT COUNT(*) FROM email_suggestions WHERE status='MANUAL'").fetchone()[0]
    outbox_stats = db.count_outbox_by_status(conn)
    n_ready = outbox_stats.get("READY", 0)
    n_sent = outbox_stats.get("SENT", 0)
    conn.close()
except Exception:
    n_prospects = n_messages = n_suggestions = n_found = n_manual = 0
    n_ready = n_sent = 0
    outbox_stats = {}

# Sidebar stats
st.sidebar.markdown("### 🔍 Email Finder")
st.sidebar.markdown(
    f"👥 **{n_prospects}** prospects  \n"
    f"📧 **{n_found + n_manual}** emails trouvés"
)

st.sidebar.markdown("### 📤 Campagne")
st.sidebar.markdown(
    f"💬 **{n_messages}** messages  \n"
    f"✉️ **{n_ready}** prêts · **{n_sent}** envoyés"
)

# SMTP config check
from dotenv import load_dotenv
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)
smtp_configured = bool(os.getenv("SMTP_USER")) and bool(os.getenv("SMTP_APP_PASSWORD"))

st.sidebar.markdown("---")

# Background task progress
task_progress = read_progress()
if task_progress.get("running"):
    st.sidebar.markdown("### 🔄 Tâche en cours")
    task_name = task_progress.get("task_name", "Tâche")
    current = task_progress.get("current", 0)
    total = task_progress.get("total", 1)
    message = task_progress.get("message", "")
    pct = current / max(total, 1)
    st.sidebar.progress(pct)
    st.sidebar.caption(f"**{task_name}** — {current}/{total}")
    st.sidebar.caption(message)
elif task_progress.get("finished_at") and not task_progress.get("error"):
    results = task_progress.get("results", {})
    if results and results.get("total", 0) > 0:
        st.sidebar.success(
            f"✅ Recherche terminée : "
            f"{results.get('found', 0)}/{results.get('total', 0)} trouvés"
        )

st.sidebar.markdown("---")

# Reset database button
if st.sidebar.button("🗑️ Réinitialiser la base", width="stretch"):
    st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset"):
    st.sidebar.warning("⚠️ Cela supprime toutes les données. Confirmer ?")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("✅ Oui", key="btn_reset_yes"):
            db.reset_db()
            st.session_state["confirm_reset"] = False
            st.sidebar.success("Base réinitialisée.")
            st.rerun()
    with col2:
        if st.button("❌ Non", key="btn_reset_no"):
            st.session_state["confirm_reset"] = False
            st.rerun()

# ---------------------------------------------------------------------------
# Main page – Visual workflow dashboard
# ---------------------------------------------------------------------------
st.markdown("# 📧 B2B Email Campaign")
st.markdown("Deux outils distincts : **Email Finder** pour trouver des adresses, et **Campagne Email** pour envoyer.")
st.markdown("")

# ── Additional stats for dashboard ─────────────────────
try:
    conn = db.get_connection()
    n_imported = conn.execute(
        "SELECT COUNT(*) FROM email_suggestions WHERE status='IMPORTED'"
    ).fetchone()[0]
    n_not_found = conn.execute(
        "SELECT COUNT(*) FROM email_suggestions WHERE status='NOT_FOUND'"
    ).fetchone()[0]
    conn.close()
except Exception:
    n_imported = n_not_found = 0

# ── Two-section layout ─────────────────────────────────
st.markdown("""
<style>
.section-card {
    background: linear-gradient(135deg, #f8f9fa, #ffffff);
    border: 2px solid #e0e4e8;
    border-radius: 16px;
    padding: 1.8rem;
    transition: box-shadow 0.2s, transform 0.15s;
    height: 100%;
}
.section-card:hover {
    box-shadow: 0 6px 20px rgba(0,0,0,0.12);
    transform: translateY(-3px);
}
.section-card.finder  { border-top: 5px solid #3498db; }
.section-card.campaign { border-top: 5px solid #2ecc71; }
.section-icon { font-size: 2.8rem; margin-bottom: 0.6rem; }
.section-title { font-weight: 800; font-size: 1.3rem; margin-bottom: 0.3rem; }
.section-desc  { font-size: 0.9rem; color: #666; margin-bottom: 0.8rem; }
.section-steps { font-size: 0.82rem; color: #888; line-height: 1.8; }
.section-stat {
    display: inline-block; font-size: 0.78rem; padding: 3px 10px;
    border-radius: 10px; font-weight: 600; margin-top: 0.6rem;
}
.stat-blue { background: #d6eaf8; color: #2471a3; }
.stat-green { background: #d5f5e3; color: #1e8449; }
</style>
""", unsafe_allow_html=True)

col_finder, col_campaign = st.columns(2)

with col_finder:
    finder_metric = f"{n_found + n_manual} / {n_prospects} emails trouvés" if n_prospects else "Aucun prospect"
    st.markdown(f"""
    <div class="section-card finder">
        <div class="section-icon">🔍</div>
        <div class="section-title">Email Finder</div>
        <div class="section-desc">
            Trouvez les adresses email professionnelles de vos prospects
        </div>
        <div class="section-steps">
            <strong>Étapes :</strong><br>
            1. Importez des prospects (prénom, nom, entreprise)<br>
            2. Lancez la recherche automatique (Hunter.io + SMTP)<br>
            3. Exportez le résultat en CSV
        </div>
        <div class="section-stat stat-blue">{finder_metric}</div>
    </div>
    """, unsafe_allow_html=True)

with col_campaign:
    campaign_metric = f"{n_ready} prêts · {n_sent} envoyés" if n_ready + n_sent else f"{n_imported} importés avec email"
    st.markdown(f"""
    <div class="section-card campaign">
        <div class="section-icon">📤</div>
        <div class="section-title">Campagne Email</div>
        <div class="section-desc">
            Envoyez des emails en masse à vos prospects
        </div>
        <div class="section-steps">
            <strong>Étapes :</strong><br>
            1. Importez prospects <strong>avec emails</strong> + messages<br>
            2. Construisez l'outbox (association auto)<br>
            3. Envoyez via SMTP → Suivez les bounces
        </div>
        <div class="section-stat stat-green">{campaign_metric}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("")
st.markdown("")

# ── Quick stats ────────────────────────────────────────
st.markdown("### 📊 Vue d'ensemble")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("👥 Prospects", n_prospects)
c2.metric("📧 Emails trouvés", n_found + n_manual)
c3.metric("📥 Importés direct", n_imported)
c4.metric("✉️ Prêts", n_ready)
c5.metric("🚀 Envoyés", n_sent)

if outbox_stats:
    st.markdown("**Détail outbox :**")
    status_labels = {
        "READY": "📬 Prêts",
        "SENT": "✅ Envoyés",
        "ERROR": "⚠️ Erreurs",
        "BOUNCED": "↩️ Bounces",
        "INVALID": "❌ Invalides",
    }
    ocols = st.columns(len(outbox_stats))
    for i, (status, count) in enumerate(sorted(outbox_stats.items())):
        label = status_labels.get(status, status)
        ocols[i].metric(label, count)

# ── Config warning ─────────────────────────────────────
if not smtp_configured:
    st.markdown("---")
    st.warning(
        "⚙️ **SMTP non configuré** — Allez dans **Réglages** pour configurer "
        "votre serveur d'envoi avant d'envoyer des emails."
    )

