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
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("B2B Email Campaign")
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Workflow**\n"
    "1. Import Data\n"
    "2. Find Emails\n"
    "3. Prepare Outbox\n"
    "4. Send Emails\n"
    "5. Track Bounces\n"
    "6. Outbox Table\n"
    "7. Settings"
)
st.sidebar.markdown("---")

# Reset database button
if st.sidebar.button("Reset database"):
    st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset"):
    st.sidebar.warning("Cette action supprime toutes les donnees. Confirmer ?")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("Oui, reset"):
            db.reset_db()
            st.session_state["confirm_reset"] = False
            st.sidebar.success("Base de donnees reinitialisee.")
            st.rerun()
    with col2:
        if st.button("Annuler"):
            st.session_state["confirm_reset"] = False
            st.rerun()

# ---------------------------------------------------------------------------
# Main page content
# ---------------------------------------------------------------------------
st.title("B2B Email Campaign Tool")
st.markdown(
    """
Bienvenue dans l'outil de campagne email B2B.

**Etapes du workflow :**

| Etape | Page | Description |
|-------|------|-------------|
| 1 | Import Data | Importer les fichiers prospects et messages |
| 2 | Find Emails | Trouver les domaines, patterns et emails pour chaque prospect |
| 3 | Prepare Outbox | Construire la file d'envoi (merge emails + messages) |
| 4 | Send Emails | Envoyer les emails READY via SMTP |
| 5 | Track Bounces | Verifier les bounces via IMAP |
| 6 | Outbox Table | Voir et exporter la table outbox |
| 7 | Settings | Configurer SMTP / IMAP / parametres |

Utilisez le menu lateral (sidebar) pour naviguer entre les pages.
"""
)

# Quick stats
try:
    conn = db.get_connection()
    n_prospects = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    n_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    n_suggestions = conn.execute("SELECT COUNT(*) FROM email_suggestions").fetchone()[0]
    outbox_stats = db.count_outbox_by_status(conn)
    conn.close()

    st.markdown("### Etat actuel de la base")
    c1, c2, c3 = st.columns(3)
    c1.metric("Prospects", n_prospects)
    c2.metric("Messages", n_messages)
    c3.metric("Suggestions email", n_suggestions)

    if outbox_stats:
        st.markdown("**Outbox :**")
        cols = st.columns(len(outbox_stats))
        for i, (status, count) in enumerate(sorted(outbox_stats.items())):
            cols[i].metric(status, count)
except Exception as e:
    st.error(f"Erreur lors du chargement des stats : {e}")
