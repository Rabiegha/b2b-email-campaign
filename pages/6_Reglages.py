"""
Page 6 -- Réglages
Configuration SMTP/IMAP et paramètres d'envoi.
"""

import streamlit as st
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv, set_key, find_dotenv

from engine.mailer import test_smtp_connection
from engine.bounce_tracker import test_imap_connection

st.set_page_config(page_title="Réglages", page_icon="⚙️", layout="wide")
st.title("6 — ⚙️ Réglages")

# ---------------------------------------------------------------------------
# Load current .env
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

if not os.path.exists(ENV_PATH):
    with open(ENV_PATH, "w") as f:
        f.write("# B2B Email Campaign Configuration\n")

load_dotenv(ENV_PATH, override=True)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── Status check ──────────────────────────────────────
smtp_ok = bool(_env("SMTP_USER")) and bool(_env("SMTP_APP_PASSWORD"))
imap_ok = bool(_env("IMAP_HOST")) and bool(_env("IMAP_USER", _env("SMTP_USER")))
hunter_configured = bool(_env("HUNTER_API_KEY"))

c1, c2, c3 = st.columns(3)
c1.metric("📤 SMTP", "✅ Configuré" if smtp_ok else "❌ Non configuré")
c2.metric("📥 IMAP", "✅ Configuré" if imap_ok else "❌ Non configuré")
c3.metric("🔍 Hunter.io", "✅ Configuré" if hunter_configured else "⚡ Optionnel")

if not smtp_ok:
    st.warning(
        "⚠️ Configurez d'abord votre SMTP ci-dessous pour pouvoir envoyer des emails."
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# SMTP Settings
# ---------------------------------------------------------------------------
st.header("📤 SMTP — Envoi d'emails")
st.caption("Gmail / Google Workspace avec un mot de passe d'application")

with st.form("smtp_form"):
    smtp_user = st.text_input("📧 Adresse email (expéditeur)", value=_env("SMTP_USER"),
                               placeholder="votre.email@gmail.com")
    smtp_password = st.text_input("🔑 Mot de passe d'application", value=_env("SMTP_APP_PASSWORD"),
                                   type="password")
    col_host, col_port = st.columns([3, 1])
    with col_host:
        smtp_host = st.text_input("🌐 Serveur SMTP", value=_env("SMTP_HOST", "smtp.gmail.com"))
    with col_port:
        smtp_port = st.text_input("🔌 Port", value=_env("SMTP_PORT", "587"))

    if st.form_submit_button("💾 Sauvegarder SMTP", width="stretch"):
        set_key(ENV_PATH, "SMTP_USER", smtp_user)
        set_key(ENV_PATH, "SMTP_APP_PASSWORD", smtp_password)
        set_key(ENV_PATH, "SMTP_HOST", smtp_host)
        set_key(ENV_PATH, "SMTP_PORT", smtp_port)
        load_dotenv(ENV_PATH, override=True)
        st.success("✅ Configuration SMTP sauvegardée.")

if st.button("🧪 Tester la connexion SMTP", width="stretch"):
    load_dotenv(ENV_PATH, override=True)
    with st.spinner("Test en cours…"):
        success, msg = test_smtp_connection()
    if success:
        st.success(f"✅ {msg}")
    else:
        st.error(f"❌ {msg}")

st.markdown("---")

# ---------------------------------------------------------------------------
# IMAP Settings
# ---------------------------------------------------------------------------
st.header("📥 IMAP — Suivi des bounces")
st.caption("Pour détecter les adresses invalides après l'envoi")

with st.form("imap_form"):
    col_ihost, col_iport = st.columns([3, 1])
    with col_ihost:
        imap_host = st.text_input("🌐 Serveur IMAP", value=_env("IMAP_HOST", "imap.gmail.com"))
    with col_iport:
        imap_port = st.text_input("🔌 Port", value=_env("IMAP_PORT", "993"))
    imap_user = st.text_input("📧 Utilisateur IMAP", value=_env("IMAP_USER", _env("SMTP_USER")))
    imap_password = st.text_input("🔑 Mot de passe", value=_env("IMAP_PASSWORD", _env("SMTP_APP_PASSWORD")),
                                   type="password")
    imap_folder = st.text_input("📂 Dossier", value=_env("IMAP_FOLDER", "INBOX"))

    if st.form_submit_button("💾 Sauvegarder IMAP", width="stretch"):
        set_key(ENV_PATH, "IMAP_HOST", imap_host)
        set_key(ENV_PATH, "IMAP_PORT", imap_port)
        set_key(ENV_PATH, "IMAP_USER", imap_user)
        set_key(ENV_PATH, "IMAP_PASSWORD", imap_password)
        set_key(ENV_PATH, "IMAP_FOLDER", imap_folder)
        load_dotenv(ENV_PATH, override=True)
        st.success("✅ Configuration IMAP sauvegardée.")

if st.button("🧪 Tester la connexion IMAP", width="stretch"):
    load_dotenv(ENV_PATH, override=True)
    with st.spinner("Test en cours…"):
        success, msg = test_imap_connection()
    if success:
        st.success(f"✅ {msg}")
    else:
        st.error(f"❌ {msg}")

st.markdown("---")

# ---------------------------------------------------------------------------
# Hunter.io API
# ---------------------------------------------------------------------------
st.header("🔍 Hunter.io — Recherche d'emails")
st.caption(
    "Optionnel mais **fortement recommandé**. Hunter.io fournit les patterns "
    "d'emails des entreprises et vérifie les adresses. "
    "[Créer un compte gratuit (25 recherches/mois)](https://hunter.io/)"
)

hunter_key = _env("HUNTER_API_KEY")
hunter_ok = bool(hunter_key)
st.metric("🔑 Hunter.io", "✅ Clé configurée" if hunter_ok else "⚡ Non configuré (optionnel)")

with st.form("hunter_form"):
    hunter_input = st.text_input(
        "🔑 Clé API Hunter.io", value=hunter_key,
        type="password",
        placeholder="Collez votre clé API ici…",
    )
    st.markdown(
        "Sans Hunter.io, l'app utilise la **vérification SMTP** et le **crawl web** "
        "pour trouver les emails. Avec Hunter.io, les résultats sont bien meilleurs."
    )
    if st.form_submit_button("💾 Sauvegarder", width="stretch"):
        set_key(ENV_PATH, "HUNTER_API_KEY", hunter_input)
        load_dotenv(ENV_PATH, override=True)
        st.success("✅ Clé Hunter.io sauvegardée.")

if hunter_ok:
    if st.button("🧪 Tester Hunter.io", width="stretch"):
        with st.spinner("Test en cours…"):
            try:
                import requests as rq
                resp = rq.get(
                    "https://api.hunter.io/v2/account",
                    params={"api_key": hunter_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    calls = data.get("requests", {})
                    used = calls.get("searches", {}).get("used", 0)
                    avail = calls.get("searches", {}).get("available", 0)
                    st.success(f"✅ Connexion OK — {used}/{avail} recherches utilisées ce mois")
                elif resp.status_code == 401:
                    st.error("❌ Clé API invalide")
                else:
                    st.error(f"❌ Erreur {resp.status_code}")
            except Exception as e:
                st.error(f"❌ Erreur: {e}")

st.markdown("---")

# ---------------------------------------------------------------------------
# Send Parameters
# ---------------------------------------------------------------------------
st.header("⏱️ Paramètres d'envoi")
st.caption("Contrôlez le rythme d'envoi pour éviter d'être bloqué")

with st.form("send_form"):
    col_min, col_max, col_per_run = st.columns(3)
    with col_min:
        min_delay = st.number_input("⏳ Délai min (s)", min_value=0.0,
                                     value=float(_env("SEND_MIN_DELAY", "5")), step=1.0)
    with col_max:
        max_delay = st.number_input("⏳ Délai max (s)", min_value=0.0,
                                     value=float(_env("SEND_MAX_DELAY", "15")), step=1.0)
    with col_per_run:
        max_per_run = st.number_input("📊 Max par session", min_value=1,
                                       value=int(_env("SEND_MAX_PER_RUN", "50")), step=10)

    if st.form_submit_button("💾 Sauvegarder", width="stretch"):
        set_key(ENV_PATH, "SEND_MIN_DELAY", str(min_delay))
        set_key(ENV_PATH, "SEND_MAX_DELAY", str(max_delay))
        set_key(ENV_PATH, "SEND_MAX_PER_RUN", str(int(max_per_run)))
        load_dotenv(ENV_PATH, override=True)
        st.success("✅ Paramètres sauvegardés.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Current .env display
# ---------------------------------------------------------------------------
with st.expander("📄 Voir le fichier .env actuel"):
    try:
        with open(ENV_PATH, "r") as f:
            content = f.read()
        display = []
        for line in content.splitlines():
            if "PASSWORD" in line.upper() and "=" in line:
                key, _, val = line.partition("=")
                if val.strip():
                    display.append(f"{key}=****")
                else:
                    display.append(line)
            else:
                display.append(line)
        st.code("\n".join(display), language="bash")
    except FileNotFoundError:
        st.info("Fichier .env non trouvé.")
