"""
Page 7 -- Settings
Configure SMTP/IMAP credentials and send parameters via .env file.
Test connections.
"""

import streamlit as st
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv, set_key, find_dotenv

from engine.mailer import test_smtp_connection
from engine.bounce_tracker import test_imap_connection

st.set_page_config(page_title="Settings", layout="wide")
st.title("7 -- Settings")

# ---------------------------------------------------------------------------
# Load current .env
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# Create .env if it doesn't exist
if not os.path.exists(ENV_PATH):
    with open(ENV_PATH, "w") as f:
        f.write("# B2B Email Campaign Configuration\n")

load_dotenv(ENV_PATH, override=True)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ---------------------------------------------------------------------------
# SMTP Settings
# ---------------------------------------------------------------------------
st.header("SMTP (envoi)")
st.markdown("Utilise Gmail / Google Workspace avec un App Password.")

with st.form("smtp_form"):
    smtp_user = st.text_input("SMTP_USER (email)", value=_env("SMTP_USER"))
    smtp_password = st.text_input("SMTP_APP_PASSWORD", value=_env("SMTP_APP_PASSWORD"), type="password")
    smtp_host = st.text_input("SMTP_HOST", value=_env("SMTP_HOST", "smtp.gmail.com"))
    smtp_port = st.text_input("SMTP_PORT", value=_env("SMTP_PORT", "587"))

    if st.form_submit_button("Sauvegarder SMTP"):
        set_key(ENV_PATH, "SMTP_USER", smtp_user)
        set_key(ENV_PATH, "SMTP_APP_PASSWORD", smtp_password)
        set_key(ENV_PATH, "SMTP_HOST", smtp_host)
        set_key(ENV_PATH, "SMTP_PORT", smtp_port)
        load_dotenv(ENV_PATH, override=True)
        st.success("Configuration SMTP sauvegardee.")

if st.button("Tester la connexion SMTP"):
    load_dotenv(ENV_PATH, override=True)
    success, msg = test_smtp_connection()
    if success:
        st.success(msg)
    else:
        st.error(msg)

st.markdown("---")

# ---------------------------------------------------------------------------
# IMAP Settings
# ---------------------------------------------------------------------------
st.header("IMAP (bounces)")

with st.form("imap_form"):
    imap_host = st.text_input("IMAP_HOST", value=_env("IMAP_HOST", "imap.gmail.com"))
    imap_port = st.text_input("IMAP_PORT", value=_env("IMAP_PORT", "993"))
    imap_user = st.text_input("IMAP_USER", value=_env("IMAP_USER", _env("SMTP_USER")))
    imap_password = st.text_input("IMAP_PASSWORD", value=_env("IMAP_PASSWORD", _env("SMTP_APP_PASSWORD")), type="password")
    imap_folder = st.text_input("IMAP_FOLDER", value=_env("IMAP_FOLDER", "INBOX"))

    if st.form_submit_button("Sauvegarder IMAP"):
        set_key(ENV_PATH, "IMAP_HOST", imap_host)
        set_key(ENV_PATH, "IMAP_PORT", imap_port)
        set_key(ENV_PATH, "IMAP_USER", imap_user)
        set_key(ENV_PATH, "IMAP_PASSWORD", imap_password)
        set_key(ENV_PATH, "IMAP_FOLDER", imap_folder)
        load_dotenv(ENV_PATH, override=True)
        st.success("Configuration IMAP sauvegardee.")

if st.button("Tester la connexion IMAP"):
    load_dotenv(ENV_PATH, override=True)
    success, msg = test_imap_connection()
    if success:
        st.success(msg)
    else:
        st.error(msg)

st.markdown("---")

# ---------------------------------------------------------------------------
# Send Parameters
# ---------------------------------------------------------------------------
st.header("Parametres d'envoi")

with st.form("send_form"):
    min_delay = st.number_input("SEND_MIN_DELAY (secondes)", min_value=0.0, value=float(_env("SEND_MIN_DELAY", "5")), step=1.0)
    max_delay = st.number_input("SEND_MAX_DELAY (secondes)", min_value=0.0, value=float(_env("SEND_MAX_DELAY", "15")), step=1.0)
    max_per_run = st.number_input("SEND_MAX_PER_RUN", min_value=1, value=int(_env("SEND_MAX_PER_RUN", "50")), step=10)

    if st.form_submit_button("Sauvegarder parametres"):
        set_key(ENV_PATH, "SEND_MIN_DELAY", str(min_delay))
        set_key(ENV_PATH, "SEND_MAX_DELAY", str(max_delay))
        set_key(ENV_PATH, "SEND_MAX_PER_RUN", str(int(max_per_run)))
        load_dotenv(ENV_PATH, override=True)
        st.success("Parametres d'envoi sauvegardes.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Current .env display
# ---------------------------------------------------------------------------
st.header("Fichier .env actuel")
try:
    with open(ENV_PATH, "r") as f:
        content = f.read()
    # Mask passwords
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
    st.info("Fichier .env non trouve.")
