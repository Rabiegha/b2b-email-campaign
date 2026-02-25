"""
Page 4 – Envoi d'emails avec sélection individuelle.
"""

import streamlit as st
import json
import os
import threading
import time
import pandas as pd
from datetime import datetime

from engine import db
from engine.mailer import send_ready_emails, test_smtp_connection

# ── Paths ──────────────────────────────────────────────────────────────
_PROGRESS_FILE = os.path.join("data", "send_progress.json")


def _write_send_progress(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(_PROGRESS_FILE, "w") as f:
        json.dump(data, f)


def _read_send_progress() -> dict | None:
    if not os.path.exists(_PROGRESS_FILE):
        return None
    try:
        with open(_PROGRESS_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _clear_send_progress():
    if os.path.exists(_PROGRESS_FILE):
        os.remove(_PROGRESS_FILE)


def _launch_send(outbox_ids: list[int], min_delay: float, max_delay: float):
    """Start the sending thread."""
    stop_flag = threading.Event()
    st.session_state["stop_flag"] = stop_flag

    log_entries = []

    def progress_cb(current, total, email, status, next_delay):
        log_entries.append({"email": email, "status": status})
        _write_send_progress({
            "status": "running",
            "current": current,
            "total": total,
            "last_email": email,
            "last_status": status,
            "next_delay": next_delay,
            "log": log_entries[-100:],
        })

    def worker():
        try:
            stats = send_ready_emails(
                progress_callback=progress_cb,
                min_delay=min_delay,
                max_delay=max_delay,
                stop_flag=stop_flag,
                outbox_ids=outbox_ids,
            )
            _write_send_progress({
                "status": "finished",
                "stats": {
                    "sent": stats["sent"],
                    "errors": stats["errors"],
                    "elapsed": stats.get("elapsed", 0),
                },
                "log": log_entries,
            })
        except Exception as e:
            _write_send_progress({
                "status": "finished",
                "stats": {"sent": 0, "errors": 0, "elapsed": 0},
                "error": str(e),
                "log": log_entries,
            })

    _write_send_progress({
        "status": "running",
        "current": 0,
        "total": len(outbox_ids),
        "last_email": "",
        "last_status": "",
        "next_delay": 0,
        "log": [],
    })

    t = threading.Thread(target=worker, daemon=True)
    t.start()


# ── Page config ────────────────────────────────────────────────────────
st.set_page_config(page_title="Envoi", page_icon="✉️", layout="wide")
st.title("✉️ Envoi d'emails")

conn = db.get_connection()
counts = db.count_outbox_by_status(conn)
n_ready = counts.get("READY", 0)
n_sent = counts.get("SENT", 0)
n_error = counts.get("ERROR", 0)
n_total = sum(counts.values())

# ── Stats bar ──────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("📬 Prêts", n_ready)
c2.metric("✅ Envoyés", n_sent)
c3.metric("❌ Erreurs", n_error)
c4.metric("📊 Total", n_total)

st.divider()

# ── Check if sending in progress ──────────────────────────────────────
progress_data = _read_send_progress()
is_sending = progress_data is not None and progress_data.get("status") == "running"

if is_sending:
    st.info("⏳ **Envoi en cours…** Veuillez patienter.")
    prog = progress_data
    current = prog.get("current", 0)
    total = prog.get("total", 1)
    pct = current / total if total > 0 else 0

    st.progress(pct, text=f"{current}/{total} emails traités")

    last_email = prog.get("last_email", "")
    last_status = prog.get("last_status", "")
    if last_email:
        icon = "✅" if last_status == "SENT" else "❌"
        st.write(f"Dernier : {icon} {last_email}")

    log = prog.get("log", [])
    if log:
        with st.expander(f"📋 Journal ({len(log)} entrées)", expanded=False):
            for entry in reversed(log[-50:]):
                icon = "✅" if entry.get("status") == "SENT" else "❌"
                st.text(f"{icon} {entry.get('email', '?')} — {entry.get('status', '?')}")

    if st.button("🔄 Rafraîchir", key="refresh_progress"):
        st.rerun()

    # Stop button
    if st.button("🛑 Arrêter l'envoi", type="secondary"):
        if "stop_flag" in st.session_state and st.session_state["stop_flag"]:
            st.session_state["stop_flag"].set()
            st.warning("⏸️ Arrêt demandé… les emails en cours seront terminés.")

    conn.close()
    st.stop()

# ── Show finished results if any ──────────────────────────────────────
if progress_data and progress_data.get("status") == "finished":
    stats = progress_data.get("stats", {})
    st.success(
        f"✅ **Envoi terminé** — {stats.get('sent', 0)} envoyés, "
        f"{stats.get('errors', 0)} erreurs "
        f"({stats.get('elapsed', 0):.1f}s)"
    )
    log = progress_data.get("log", [])
    if log:
        with st.expander(f"📋 Journal du dernier envoi ({len(log)})", expanded=False):
            for entry in reversed(log):
                icon = "✅" if entry.get("status") == "SENT" else "❌"
                st.text(f"{icon} {entry.get('email', '?')} — {entry.get('status', '?')}")
    _clear_send_progress()
    st.rerun()

# ── No READY emails ───────────────────────────────────────────────────
if n_ready == 0:
    st.warning("📭 Aucun email prêt à envoyer. Préparez l'outbox d'abord (page Outbox).")
    conn.close()
    st.stop()

# ── SMTP quick check ──────────────────────────────────────────────────
smtp_user = os.getenv("SMTP_USER", "")
smtp_pass = os.getenv("SMTP_APP_PASSWORD", "")
if not smtp_user or not smtp_pass:
    st.error("⚠️ SMTP non configuré. Allez dans **Réglages** pour configurer vos identifiants.")
    conn.close()
    st.stop()

# ═══════════════════════════════════════════════════════════════════════
# SECTION: Sélection des emails à envoyer
# ═══════════════════════════════════════════════════════════════════════
st.subheader("📋 Sélection des emails à envoyer")

ready_rows = db.get_outbox(conn, status_filter="READY")

# Build a DataFrame with a checkbox column
rows_data = []
for r in ready_rows:
    rows_data.append({
        "id": r["id"],
        "✅": True,  # Selected by default
        "Entreprise": r["company"] or "",
        "Email": r["email"],
        "Objet": r["subject"] or "",
        "Prénom": r["firstname"] or "",
        "Nom": r["lastname"] or "",
    })

df_ready = pd.DataFrame(rows_data)

if df_ready.empty:
    st.info("Aucun email READY trouvé.")
    conn.close()
    st.stop()

# Select / Deselect all buttons
col_sel1, col_sel2, col_sel3 = st.columns([1, 1, 4])
with col_sel1:
    if st.button("☑️ Tout sélectionner"):
        st.session_state["select_all_action"] = "all"
        st.rerun()
with col_sel2:
    if st.button("⬜ Tout désélectionner"):
        st.session_state["select_all_action"] = "none"
        st.rerun()

# Apply select/deselect if requested
if st.session_state.get("select_all_action") == "all":
    df_ready["✅"] = True
    del st.session_state["select_all_action"]
elif st.session_state.get("select_all_action") == "none":
    df_ready["✅"] = False
    del st.session_state["select_all_action"]

# Editable table
edited_df = st.data_editor(
    df_ready,
    column_config={
        "id": None,  # Hidden
        "✅": st.column_config.CheckboxColumn("✅ Envoyer", default=True),
        "Entreprise": st.column_config.TextColumn("Entreprise", disabled=True),
        "Email": st.column_config.TextColumn("Email", disabled=True),
        "Objet": st.column_config.TextColumn("Objet", disabled=True, width="large"),
        "Prénom": st.column_config.TextColumn("Prénom", disabled=True),
        "Nom": st.column_config.TextColumn("Nom", disabled=True),
    },
    hide_index=True,
    use_container_width=True,
    key="email_selection_editor",
    num_rows="fixed",
)

# Compute selected IDs
selected_mask = edited_df["✅"] == True
selected_ids = edited_df.loc[selected_mask, "id"].tolist()
n_selected = len(selected_ids)

st.info(f"**{n_selected}** / {len(df_ready)} emails sélectionnés")

# ═══════════════════════════════════════════════════════════════════════
# SECTION: Paramètres d'envoi
# ═══════════════════════════════════════════════════════════════════════
st.subheader("⚙️ Paramètres d'envoi")

col_d1, col_d2 = st.columns(2)
with col_d1:
    min_delay = st.slider(
        "⏱️ Délai minimum (sec)", 1, 60,
        value=int(float(os.getenv("SEND_MIN_DELAY", "5"))),
        help="Temps d'attente minimal entre chaque email"
    )
with col_d2:
    max_delay = st.slider(
        "⏱️ Délai maximum (sec)", 1, 120,
        value=int(float(os.getenv("SEND_MAX_DELAY", "15"))),
        help="Temps d'attente maximal entre chaque email"
    )

if max_delay < min_delay:
    max_delay = min_delay

# Time estimate
avg_delay = (min_delay + max_delay) / 2
estimated_seconds = n_selected * avg_delay
est_min = int(estimated_seconds // 60)
est_sec = int(estimated_seconds % 60)
st.caption(f"⏱️ Temps estimé : **{est_min}min {est_sec}s** (pour {n_selected} emails)")

# ═══════════════════════════════════════════════════════════════════════
# SECTION: Lancer l'envoi
# ═══════════════════════════════════════════════════════════════════════
st.divider()

col_send, col_test = st.columns([2, 1])

with col_test:
    if st.button("🔌 Tester SMTP"):
        with st.spinner("Test en cours…"):
            ok, msg = test_smtp_connection()
        if ok:
            st.success(f"✅ {msg}")
        else:
            st.error(f"❌ {msg}")

with col_send:
    send_disabled = n_selected == 0
    if st.button(
        f"🚀 Envoyer {n_selected} email{'s' if n_selected > 1 else ''}",
        type="primary",
        disabled=send_disabled,
        use_container_width=True
    ):
        # Confirm
        st.session_state["confirm_send"] = True
        st.session_state["send_ids"] = selected_ids
        st.session_state["send_min_delay"] = min_delay
        st.session_state["send_max_delay"] = max_delay

# Confirmation dialog
if st.session_state.get("confirm_send"):
    ids_to_send = st.session_state.get("send_ids", [])
    n = len(ids_to_send)
    st.warning(f"⚠️ Vous allez envoyer **{n}** email{'s' if n > 1 else ''}. Confirmez-vous ?")

    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ Oui, envoyer", type="primary", use_container_width=True):
            st.session_state["confirm_send"] = False
            _launch_send(
                ids_to_send,
                st.session_state.get("send_min_delay", 5),
                st.session_state.get("send_max_delay", 15),
            )
            st.rerun()
    with col_no:
        if st.button("❌ Annuler", use_container_width=True):
            st.session_state["confirm_send"] = False
            st.rerun()

conn.close()

# ═══════════════════════════════════════════════════════════════════════
# SECTION: Table outbox complète
# ═══════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("📊 Table Outbox complète")

conn2 = db.get_connection()

# Filter
filter_col1, filter_col2 = st.columns([1, 3])
with filter_col1:
    status_filter = st.selectbox(
        "Statut", ["Tous", "READY", "SENT", "ERROR", "BOUNCED", "INVALID"],
        key="outbox_status_filter"
    )
with filter_col2:
    search_text = st.text_input("🔍 Rechercher", key="outbox_search", placeholder="entreprise, email, objet…")

sf = status_filter if status_filter != "Tous" else None
all_rows = db.get_outbox(conn2, status_filter=sf, search_text=search_text if search_text else None)

if all_rows:
    outbox_data = []
    for r in all_rows:
        status_icon = {"READY": "📬", "SENT": "✅", "ERROR": "❌", "BOUNCED": "📛", "INVALID": "🚫"}.get(r["status"], "❓")
        outbox_data.append({
            "Statut": f"{status_icon} {r['status']}",
            "Entreprise": r["company"] or "",
            "Email": r["email"],
            "Objet": r["subject"] or "",
            "Envoyé le": r["sent_at"] or "",
            "Erreur": r["error_message"] or "",
        })
    df_outbox = pd.DataFrame(outbox_data)
    st.dataframe(df_outbox, use_container_width=True, hide_index=True)
    st.caption(f"{len(outbox_data)} ligne(s)")

    # Export CSV
    csv = df_outbox.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Exporter CSV",
        data=csv,
        file_name=f"outbox_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv"
    )
else:
    st.info("Aucune donnée dans l'outbox.")

conn2.close()
