"""
Page 2 -- 📤 Campagne Email
Importez des prospects AVEC leurs emails + messages, puis passez
directement à l'outbox / envoi. Les deux imports sont visibles côte à côte.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.normalize import normalize_company
from engine.io_utils import (
    read_upload, detect_prospect_with_email_columns,
    detect_message_columns, validate_mapping,
    rows_to_dataframe, df_to_csv_bytes,
)

st.set_page_config(page_title="Campagne Email", page_icon="📤", layout="wide")
st.title("📤 Campagne Email")
st.caption("Importez vos prospects (avec emails) et vos messages, puis construisez votre campagne.")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Helpers fichier persistant ──────────────────────────
def _save_uploaded_file(uploaded_file, prefix: str) -> str:
    dest = os.path.join(UPLOAD_DIR, f"{prefix}_{uploaded_file.name}")
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(prefix):
            os.remove(os.path.join(UPLOAD_DIR, fname))
    with open(dest, "wb") as f:
        uploaded_file.seek(0)
        f.write(uploaded_file.read())
    uploaded_file.seek(0)
    return dest


def _load_saved_file(prefix: str) -> pd.DataFrame | None:
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(prefix):
            path = os.path.join(UPLOAD_DIR, fname)
            try:
                if fname.endswith(".csv"):
                    for enc in ("utf-8", "latin-1", "cp1252"):
                        try:
                            return pd.read_csv(path, encoding=enc)
                        except UnicodeDecodeError:
                            continue
                elif fname.endswith((".xlsx", ".xls")):
                    return pd.read_excel(path, engine="openpyxl")
            except Exception:
                pass
    return None


def _get_saved_filename(prefix: str) -> str | None:
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(prefix):
            return fname.replace(f"{prefix}_", "", 1)
    return None


def _clear_saved_file(prefix: str):
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(prefix):
            os.remove(os.path.join(UPLOAD_DIR, fname))


def _guess_pattern(firstname: str, lastname: str, email_prefix: str) -> str:
    """Guess the email pattern from the prefix and the name."""
    fn = firstname.strip().lower()
    ln = lastname.strip().lower()
    prefix = email_prefix.strip().lower()
    if not fn or not ln:
        return "unknown"
    fn1 = fn[0]
    patterns = {
        f"{fn}.{ln}": "prenom.nom",
        f"{fn}{ln}": "prenomnom",
        f"{fn1}.{ln}": "p.nom",
        f"{fn1}{ln}": "pnom",
        f"{fn}": "prenom",
        f"{ln}.{fn}": "nom.prenom",
        f"{ln}{fn}": "nomprenom",
        f"{ln}": "nom",
        f"{fn}_{ln}": "prenom_nom",
        f"{fn}-{ln}": "prenom-nom",
    }
    for prefix_pattern, name in patterns.items():
        if prefix == prefix_pattern:
            return name
    return "unknown"


# ── Stats ──────────────────────────────────────────────
try:
    conn = db.get_connection()
    n_prospects = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    n_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    n_imported = conn.execute(
        "SELECT COUNT(*) FROM email_suggestions WHERE status='IMPORTED'"
    ).fetchone()[0]
    outbox_stats = db.count_outbox_by_status(conn)
    n_outbox = sum(outbox_stats.values()) if outbox_stats else 0
    conn.close()
except Exception:
    n_prospects = n_messages = n_imported = n_outbox = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("👥 Prospects", n_prospects)
c2.metric("📧 Avec email", n_imported)
c3.metric("💬 Messages", n_messages)
c4.metric("📮 Outbox", n_outbox)

st.markdown("---")


# =========================================================================
#  DEUX COLONNES : Import Prospects (gauche) + Import Messages (droite)
# =========================================================================
col_left, col_right = st.columns(2, gap="large")

# ─────────────────────────────────────────────────────────
#  COLONNE GAUCHE : Import Prospects + Emails
# ─────────────────────────────────────────────────────────
with col_left:
    st.subheader("📥 Prospects + Emails")
    st.markdown(
        "Colonnes : **firstname**, **lastname**, **company**, **email**  \n"
        "_(synonymes acceptés : prénom, nom, entreprise, mail…)_"
    )

    file_p = st.file_uploader(
        "Fichier prospects (CSV / XLSX)", type=["csv", "xlsx", "xls"],
        key="camp_up_prospects",
    )

    if file_p is not None:
        _save_uploaded_file(file_p, "camp_prospects")
        df_p = read_upload(file_p)
    else:
        df_p = _load_saved_file("camp_prospects")
        saved_name = _get_saved_filename("camp_prospects")
        if df_p is not None:
            st.info(f"📁 Fichier chargé : **{saved_name}**")
            if st.button("🗑️ Supprimer", key="camp_clear_p"):
                _clear_saved_file("camp_prospects")
                st.rerun()

    if df_p is not None and not df_p.empty:
        mapping_p = detect_prospect_with_email_columns(df_p)
        required_keys = ["firstname", "lastname", "company", "email"]
        missing_p = [k for k in required_keys if not mapping_p.get(k)]

        st.markdown("**Colonnes détectées :**")
        for canon, orig in mapping_p.items():
            if orig:
                st.write(f"  - {canon} → `{orig}`")
            else:
                st.warning(f"  - {canon} : non trouvé !")

        if missing_p:
            if "email" in missing_p:
                st.error(
                    "⚠️ La colonne **email** est obligatoire ici.  \n"
                    "Pas d'emails ? → Utilisez **🔍 Email Finder**."
                )
            else:
                st.error(f"Colonnes manquantes : {', '.join(missing_p)}")
        else:
            conn = db.get_connection()
            existing = db.get_all_prospects(conn)
            conn.close()
            existing_set = set()
            for r in existing:
                existing_set.add((
                    str(r["firstname"]).strip().lower(),
                    str(r["lastname"]).strip().lower(),
                    normalize_company(str(r["company"]).strip()),
                ))

            statuses = []
            for _, row in df_p.iterrows():
                fn = str(row[mapping_p["firstname"]]).strip()
                ln = str(row[mapping_p["lastname"]]).strip()
                co = str(row[mapping_p["company"]]).strip()
                key = (fn.lower(), ln.lower(), normalize_company(co))
                statuses.append("🔄 Déjà" if key in existing_set else "🆕 Nouveau")

            df_preview = df_p.copy()
            df_preview.insert(0, "Statut", statuses)

            n_new = statuses.count("🆕 Nouveau")
            n_dup = statuses.count("🔄 Déjà")
            mc1, mc2 = st.columns(2)
            mc1.metric("🆕 Nouveaux", n_new)
            mc2.metric("🔄 Déjà en base", n_dup)

            st.dataframe(df_preview, height=250, hide_index=True)

            import_mode = st.radio(
                "Mode d'import",
                ["Nouveaux uniquement", "Tout (y compris doublons)"],
                key="camp_import_mode",
            )

            if st.button("✅ Importer prospects + emails", key="camp_btn_import",
                          type="primary", use_container_width=True):
                conn = db.get_connection()
                count = 0
                skipped = 0
                for _, row in df_p.iterrows():
                    fn = str(row[mapping_p["firstname"]]).strip()
                    ln = str(row[mapping_p["lastname"]]).strip()
                    co = str(row[mapping_p["company"]]).strip()
                    email = str(row[mapping_p["email"]]).strip()

                    if fn and ln and co:
                        key = (fn.lower(), ln.lower(), normalize_company(co))
                        if import_mode.startswith("Nouveaux") and key in existing_set:
                            skipped += 1
                            continue

                        ck = normalize_company(co)
                        db.insert_prospect(conn, fn, ln, co, ck)
                        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                        if email and "@" in email:
                            domain = email.split("@")[1]
                            prefix = email.split("@")[0]
                            pattern = _guess_pattern(fn, ln, prefix)
                            db.upsert_email_suggestion(
                                conn, pid, domain, pattern,
                                email, 1.0, "IMPORTED",
                                "Importé directement avec email",
                            )
                        count += 1
                conn.commit()
                conn.close()
                msg = f"✅ {count} prospect(s) importé(s)."
                if skipped:
                    msg += f" {skipped} doublon(s) ignoré(s)."
                st.success(msg)
                st.rerun()

    elif n_prospects == 0:
        st.markdown(
            '<div style="text-align:center;padding:1.5rem;color:#888;">'
            '<div style="font-size:2rem;">📤</div>'
            "<p>Glissez un fichier CSV/Excel avec<br>"
            "<strong>firstname, lastname, company, email</strong></p></div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────
#  COLONNE DROITE : Import Messages
# ─────────────────────────────────────────────────────────
with col_right:
    st.subheader("💬 Messages")
    st.markdown(
        "Colonnes : **company**, **subject**, **body_text**  \n"
        "_(synonymes : entreprise, objet, message…)_"
    )

    file_m = st.file_uploader(
        "Fichier messages (CSV / XLSX)", type=["csv", "xlsx", "xls"],
        key="camp_up_messages",
    )

    if file_m is not None:
        _save_uploaded_file(file_m, "camp_messages")
        df_m = read_upload(file_m)
    else:
        df_m = _load_saved_file("camp_messages")
        saved_name_m = _get_saved_filename("camp_messages")
        if df_m is not None:
            st.info(f"📁 Fichier chargé : **{saved_name_m}**")
            if st.button("🗑️ Supprimer", key="camp_clear_m"):
                _clear_saved_file("camp_messages")
                st.rerun()

    if df_m is not None and not df_m.empty:
        mapping_m = detect_message_columns(df_m)
        missing_m = validate_mapping(mapping_m)

        st.markdown("**Colonnes détectées :**")
        for canon, orig in mapping_m.items():
            if orig:
                st.write(f"  - {canon} → `{orig}`")
            else:
                st.warning(f"  - {canon} : non trouvé !")

        if missing_m:
            st.error(f"Colonnes manquantes : {', '.join(missing_m)}")
        else:
            st.dataframe(df_m, height=250, hide_index=True)

            conn = db.get_connection()
            existing_msgs = db.get_all_messages(conn)
            conn.close()
            existing_msg_set = set()
            for r in existing_msgs:
                existing_msg_set.add((
                    normalize_company(str(r["company"]).strip()),
                    str(r["subject"]).strip().lower(),
                ))

            n_new_m = 0
            n_dup_m = 0
            for _, row in df_m.iterrows():
                co = str(row[mapping_m["company"]]).strip()
                subj = str(row[mapping_m["subject"]]).strip()
                key = (normalize_company(co), subj.lower())
                if key in existing_msg_set:
                    n_dup_m += 1
                else:
                    n_new_m += 1

            mc1_m, mc2_m = st.columns(2)
            mc1_m.metric("🆕 Nouveaux", n_new_m)
            mc2_m.metric("🔄 Déjà en base", n_dup_m)

            if st.button("✅ Importer les messages", key="camp_btn_import_msg",
                          type="primary", use_container_width=True):
                conn = db.get_connection()
                count_m = 0
                for _, row in df_m.iterrows():
                    co = str(row[mapping_m["company"]]).strip()
                    subj = str(row[mapping_m["subject"]]).strip()
                    body = str(row[mapping_m["body_text"]]).strip()
                    if co and subj and body:
                        ck = normalize_company(co)
                        key = (ck, subj.lower())
                        if key not in existing_msg_set:
                            db.insert_message(conn, co, ck, subj, body)
                            count_m += 1
                conn.commit()
                conn.close()
                if count_m:
                    st.success(f"✅ {count_m} message(s) importé(s).")
                    st.rerun()
                else:
                    st.info("Aucun nouveau message à importer.")

    elif n_messages == 0:
        st.markdown(
            '<div style="text-align:center;padding:1.5rem;color:#888;">'
            '<div style="font-size:2rem;">💬</div>'
            "<p>Glissez un fichier CSV/Excel avec<br>"
            "<strong>company, subject, body_text</strong></p></div>",
            unsafe_allow_html=True,
        )

    # ── Saisie manuelle d'un message ────────────────────
    st.markdown("---")
    with st.expander("✏️ Saisir un message manuellement"):
        with st.form("camp_manual_msg"):
            msg_company = st.text_input("Entreprise *")
            msg_subject = st.text_input("Objet *")
            msg_body = st.text_area("Message *", height=150)
            submitted = st.form_submit_button("💾 Ajouter", type="primary")
            if submitted:
                if msg_company and msg_subject and msg_body:
                    conn = db.get_connection()
                    ck = normalize_company(msg_company)
                    db.insert_message(conn, msg_company, ck, msg_subject, msg_body)
                    conn.commit()
                    conn.close()
                    st.success("Message ajouté.")
                    st.rerun()
                else:
                    st.warning("Tous les champs sont obligatoires.")


# =========================================================================
#  CTA : Prochaine étape
# =========================================================================
if n_prospects > 0 and n_messages > 0 and n_imported > 0:
    st.markdown("---")
    st.success(
        "**👉 Prochaine étape :** Allez sur **📮 Outbox** pour construire votre "
        "liste d'envoi, puis sur **✉️ Envoi** pour expédier !"
    )


# =========================================================================
#  Base de données (en bas, en expandeur)
# =========================================================================
st.markdown("---")

with st.expander("🗃️ Gérer les prospects en base"):
    conn = db.get_connection()
    rows = db.get_all_prospects(conn)

    if rows:
        df_db = pd.DataFrame([dict(r) for r in rows])
        all_sug = conn.execute("""
            SELECT prospect_id, suggested_email, status, confidence_score
            FROM email_suggestions
        """).fetchall()
        sug_map = {}
        for s in all_sug:
            sug_map[s["prospect_id"]] = {
                "email": s["suggested_email"] or "",
                "status": s["status"],
                "confidence": s["confidence_score"] or 0,
            }
        df_db["email"] = df_db["id"].map(lambda x: sug_map.get(x, {}).get("email", ""))
        df_db["email_status"] = df_db["id"].map(lambda x: sug_map.get(x, {}).get("status", "—"))

        search_db = st.text_input("🔍 Rechercher", key="camp_search_db",
                                   placeholder="Nom, entreprise, email…")
        if search_db:
            mask = pd.Series(False, index=df_db.index)
            for col in ["firstname", "lastname", "company", "email"]:
                mask = mask | df_db[col].astype(str).str.contains(search_db, case=False, na=False)
            df_db = df_db[mask].copy()

        st.caption(f"{len(df_db)} prospect(s)")
        st.dataframe(
            df_db[["id", "firstname", "lastname", "company", "email", "email_status"]],
            height=350, hide_index=True,
            column_config={
                "email": st.column_config.TextColumn("📧 Email"),
                "email_status": st.column_config.TextColumn("Statut"),
            },
        )

        if st.button("🗑️ Supprimer TOUS les prospects", key="camp_del_all_p"):
            st.session_state["camp_confirm_del_p"] = True
        if st.session_state.get("camp_confirm_del_p"):
            st.warning("⚠️ Supprimer tous les prospects et suggestions ?")
            cy, cn = st.columns(2)
            with cy:
                if st.button("✅ Oui", key="camp_del_p_yes"):
                    db.delete_all_prospects(conn)
                    conn.commit()
                    st.session_state["camp_confirm_del_p"] = False
                    st.rerun()
            with cn:
                if st.button("❌ Non", key="camp_del_p_no"):
                    st.session_state["camp_confirm_del_p"] = False
                    st.rerun()
    else:
        st.info("Aucun prospect en base.")
    conn.close()


with st.expander("💬 Gérer les messages en base"):
    conn = db.get_connection()
    msgs = db.get_all_messages(conn)
    conn.close()

    if msgs:
        df_msgs = pd.DataFrame([dict(r) for r in msgs])
        st.caption(f"{len(df_msgs)} message(s)")

        edited_msgs = st.data_editor(
            df_msgs[["id", "company", "subject", "body_text"]],
            height=300, hide_index=True, num_rows="fixed",
            disabled=["id"], key="camp_msg_editor",
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "company": st.column_config.TextColumn("Entreprise", width="medium"),
                "subject": st.column_config.TextColumn("Objet", width="medium"),
                "body_text": st.column_config.TextColumn("Message", width="large"),
            },
        )

        col_s, col_d = st.columns(2)
        with col_s:
            if st.button("💾 Sauvegarder", key="camp_save_msgs"):
                conn = db.get_connection()
                count_up = 0
                for _, row in edited_msgs.iterrows():
                    mid = int(row["id"])
                    orig = df_msgs[df_msgs["id"] == mid]
                    if orig.empty:
                        continue
                    orig = orig.iloc[0]
                    changed = any(str(row[c]) != str(orig[c]) for c in ["company", "subject", "body_text"])
                    if changed:
                        ck = normalize_company(str(row["company"]).strip())
                        db.update_message(conn, mid,
                                          str(row["company"]).strip(), ck,
                                          str(row["subject"]).strip(),
                                          str(row["body_text"]).strip())
                        count_up += 1
                conn.commit()
                conn.close()
                if count_up:
                    st.success(f"{count_up} message(s) mis à jour.")
                    st.rerun()
                else:
                    st.info("Aucune modification.")
        with col_d:
            if st.button("🗑️ Supprimer TOUS les messages", key="camp_del_all_m"):
                st.session_state["camp_confirm_del_m"] = True
            if st.session_state.get("camp_confirm_del_m"):
                st.warning("⚠️ Supprimer tous les messages ?")
                cy, cn = st.columns(2)
                with cy:
                    if st.button("✅ Oui", key="camp_del_m_yes"):
                        conn = db.get_connection()
                        db.delete_all_messages(conn)
                        conn.commit()
                        conn.close()
                        st.session_state["camp_confirm_del_m"] = False
                        st.rerun()
                with cn:
                    if st.button("❌ Non", key="camp_del_m_no"):
                        st.session_state["camp_confirm_del_m"] = False
                        st.rerun()
    else:
        st.info("Aucun message en base.")
