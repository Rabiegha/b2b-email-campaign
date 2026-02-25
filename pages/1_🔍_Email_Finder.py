"""
Page 1 -- 🔍 Email Finder
Outil autonome : importez des prospects (prénom, nom, entreprise),
lancez la recherche d'adresses email, consultez et exportez les résultats.
"""

import streamlit as st
import pandas as pd
import time
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.normalize import normalize_company
from engine.io_utils import (
    read_upload, detect_prospect_columns, validate_mapping,
    rows_to_dataframe, df_to_csv_bytes,
)
from engine.email_pattern import PATTERN_DEFS
from engine.task_runner import run_email_search, read_progress, is_running, clear_progress

st.set_page_config(page_title="Email Finder", page_icon="🔍", layout="wide")
st.title("🔍 Email Finder")
st.caption("Trouvez les adresses email professionnelles de vos prospects")

PATTERN_NAMES = [p[0] for p in PATTERN_DEFS]
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_uploaded_file(uploaded_file, prefix: str) -> str:
    dest = os.path.join(UPLOAD_DIR, f"{prefix}_{uploaded_file.name}")
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


# ── Stats ───────────────────────────────────────────────
try:
    conn = db.get_connection()
    n_prospects = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    n_found = conn.execute(
        "SELECT COUNT(*) FROM email_suggestions WHERE status='FOUND'"
    ).fetchone()[0]
    n_manual = conn.execute(
        "SELECT COUNT(*) FROM email_suggestions WHERE status='MANUAL'"
    ).fetchone()[0]
    n_not_found = conn.execute(
        "SELECT COUNT(*) FROM email_suggestions WHERE status='NOT_FOUND'"
    ).fetchone()[0]
    n_pending = n_prospects - (n_found + n_manual + n_not_found)
    conn.close()
except Exception:
    n_prospects = n_found = n_manual = n_not_found = n_pending = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("👥 Prospects", n_prospects)
c2.metric("✅ Emails trouvés", n_found + n_manual)
c3.metric("❌ Non trouvés", n_not_found)
c4.metric("⏳ En attente", n_pending)

if n_prospects > 0:
    pct = (n_found + n_manual) / n_prospects
    st.progress(pct, text=f"{pct*100:.0f}% des prospects ont un email")

st.markdown("---")

# =========================================================================
# Tabs
# =========================================================================
tab_import, tab_search, tab_manual = st.tabs([
    "📥 Importer des prospects",
    "🚀 Recherche & Résultats",
    "✏️ Saisie manuelle",
])


# =========================================================================
# TAB 1 : Importer des prospects (sans email)
# =========================================================================
with tab_import:
    st.subheader("📥 Importer des prospects")
    st.markdown(
        "Colonnes attendues : **firstname**, **lastname**, **company** "
        "(les synonymes sont acceptés : prénom, nom, entreprise…)"
    )

    file_p = st.file_uploader(
        "Fichier prospects (CSV / XLSX)", type=["csv", "xlsx", "xls"],
        key="finder_up_prospects",
    )

    if file_p is not None:
        _save_uploaded_file(file_p, "finder_prospects")
        df_p = read_upload(file_p)
    else:
        df_p = _load_saved_file("finder_prospects")
        saved_name = _get_saved_filename("finder_prospects")
        if df_p is not None:
            st.info(f"📁 Fichier précédent chargé : **{saved_name}**")
            if st.button("🗑️ Supprimer le fichier sauvegardé", key="finder_clear_p"):
                _clear_saved_file("finder_prospects")
                st.rerun()

    if df_p is not None and not df_p.empty:
        mapping_p = detect_prospect_columns(df_p)
        missing_p = validate_mapping(mapping_p)

        st.markdown("**Colonnes détectées :**")
        for canon, orig in mapping_p.items():
            if orig:
                st.write(f"  - {canon} → `{orig}`")
            else:
                st.warning(f"  - {canon} : non trouvé !")

        if missing_p:
            st.error(f"Colonnes manquantes : {', '.join(missing_p)}")
        else:
            # Détection doublons
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
                statuses.append("🔄 Déjà en base" if key in existing_set else "🆕 Nouveau")

            df_preview = df_p.copy()
            df_preview.insert(0, "Statut", statuses)

            n_new = statuses.count("🆕 Nouveau")
            n_dup = statuses.count("🔄 Déjà en base")
            c1_p, c2_p = st.columns(2)
            c1_p.metric("🆕 Nouveaux", n_new)
            c2_p.metric("🔄 Déjà en base", n_dup)

            st.dataframe(df_preview, width="stretch", height=300)

            import_mode = st.radio(
                "Mode d'import",
                ["Importer uniquement les nouveaux", "Tout importer (y compris doublons)"],
                key="finder_import_mode",
            )

            if st.button("✅ Importer dans la base", key="finder_btn_import", type="primary"):
                conn = db.get_connection()
                count = 0
                skipped = 0
                for _, row in df_p.iterrows():
                    fn = str(row[mapping_p["firstname"]]).strip()
                    ln = str(row[mapping_p["lastname"]]).strip()
                    co = str(row[mapping_p["company"]]).strip()
                    if fn and ln and co:
                        key = (fn.lower(), ln.lower(), normalize_company(co))
                        if import_mode.startswith("Importer uniquement") and key in existing_set:
                            skipped += 1
                            continue
                        ck = normalize_company(co)
                        db.insert_prospect(conn, fn, ln, co, ck)
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
            """
            <div style="text-align:center; padding:2rem 1rem;">
                <div style="font-size:2.5rem;">📂</div>
                <h3>Importez vos prospects</h3>
                <p style="color:#888;">Glissez un fichier CSV ou Excel avec les colonnes
                <strong>firstname</strong>, <strong>lastname</strong>, <strong>company</strong></p>
            </div>
            """,
            unsafe_allow_html=True,
        )


# =========================================================================
# TAB 2 : Recherche & Résultats
# =========================================================================
with tab_search:
    if n_prospects == 0:
        st.markdown(
            """
            <div style="text-align:center; padding:3rem 1rem;">
                <div style="font-size:3rem;">🔍</div>
                <h3>Pas encore de prospects</h3>
                <p style="color:#888;">Importez d'abord vos prospects dans l'onglet
                <strong>📥 Importer</strong>.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        # ── Search launcher ────────────────────────────
        task_progress = read_progress()
        task_running = task_progress.get("running", False)

        if task_running:
            current = task_progress.get("current", 0)
            total = task_progress.get("total", 1)
            message = task_progress.get("message", "")
            pct = current / max(total, 1)
            st.info("🔄 **Recherche en cours…**")
            st.progress(pct, text=f"{message} ({current}/{total})")
            time.sleep(3)
            st.rerun()
        else:
            if task_progress.get("finished_at") and task_progress.get("results"):
                results = task_progress["results"]
                st.success(
                    f"✅ Dernière recherche : **{results.get('found', 0)}** trouvés "
                    f"sur **{results.get('total', 0)}** traités."
                )

            col_btn, col_max, col_refresh, col_clear = st.columns([2, 1, 1, 1])
            with col_btn:
                launch = st.button("🚀 Lancer la recherche", type="primary", width="stretch")
            with col_max:
                max_p = st.number_input("Max (0=tous)", min_value=0, value=0, step=10,
                                        label_visibility="collapsed")
            with col_refresh:
                force = st.checkbox("Forcer refresh")
            with col_clear:
                if task_progress.get("finished_at"):
                    if st.button("🧹 Effacer"):
                        clear_progress()
                        st.rerun()

            if launch:
                started = run_email_search(max_prospects=max_p, force_refresh=force)
                if started:
                    st.toast("Recherche lancée !", icon="🚀")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Une recherche est déjà en cours.")

        st.markdown("---")

        # ── Résultats ──────────────────────────────────
        st.subheader("📋 Résultats")

        col_f, col_s = st.columns([1, 2])
        with col_f:
            filter_status = st.selectbox(
                "Filtrer",
                ["Tous", "✅ Trouvé", "❌ Non trouvé", "✏️ Manuel", "⏳ En attente"],
                key="finder_filter",
            )
        with col_s:
            search_q = st.text_input("🔍 Rechercher", key="finder_search",
                                      placeholder="Nom, entreprise, email…")

        try:
            conn = db.get_connection()
            all_data = conn.execute("""
                SELECT p.id AS prospect_id, p.firstname, p.lastname, p.company,
                       es.id AS suggestion_id,
                       es.suggested_email, es.domain, es.pattern,
                       es.confidence_score, es.status AS email_status
                FROM prospects p
                LEFT JOIN email_suggestions es ON es.prospect_id = p.id
                ORDER BY p.company, p.lastname
            """).fetchall()
            conn.close()

            if all_data:
                df = pd.DataFrame([dict(r) for r in all_data])

                def _status_label(row):
                    s = row.get("email_status")
                    email = row.get("suggested_email")
                    if s is None:
                        return "⏳ En attente"
                    elif s == "FOUND" and email:
                        return "✅ Trouvé"
                    elif s == "MANUAL" and email:
                        return "✏️ Manuel"
                    elif s == "NOT_FOUND" or not email:
                        return "❌ Non trouvé"
                    return f"🔹 {s}"

                df["statut"] = df.apply(_status_label, axis=1)
                df["confiance"] = (df["confidence_score"].fillna(0) * 100).round(0).astype(int)

                if filter_status != "Tous":
                    df = df[df["statut"] == filter_status].copy()
                if search_q:
                    mask = pd.Series(False, index=df.index)
                    for col in ["firstname", "lastname", "company", "suggested_email"]:
                        if col in df.columns:
                            mask = mask | df[col].astype(str).str.contains(
                                search_q, case=False, na=False
                            )
                    df = df[mask]

                st.caption(f"{len(df)} prospect(s)")

                if df.empty:
                    st.info("Aucun résultat pour ces filtres.")
                else:
                    edit_cols = ["suggestion_id", "statut", "firstname", "lastname",
                                 "company", "suggested_email", "domain", "pattern",
                                 "confiance"]
                    available = [c for c in edit_cols if c in df.columns]

                    edited_df = st.data_editor(
                        df[available],
                        width="stretch",
                        num_rows="fixed",
                        disabled=["suggestion_id", "statut", "firstname", "lastname",
                                  "company", "confiance"],
                        key="finder_editor",
                        hide_index=True,
                        column_config={
                            "suggestion_id": st.column_config.NumberColumn("ID", width="small"),
                            "statut": st.column_config.TextColumn("Statut", width="small"),
                            "suggested_email": st.column_config.TextColumn("📧 Email", width="large"),
                            "pattern": st.column_config.SelectboxColumn(
                                "Pattern", options=PATTERN_NAMES + ["manual"],
                            ),
                            "confiance": st.column_config.ProgressColumn(
                                "Confiance %", min_value=0, max_value=100, format="%d%%",
                            ),
                        },
                        height=500,
                    )

                    # Save + Delete + Export
                    col_save, col_del, col_export = st.columns(3)

                    with col_save:
                        if st.button("💾 Sauvegarder", key="finder_save"):
                            conn = db.get_connection()
                            count_up = 0
                            for _, row in edited_df.iterrows():
                                sid = row.get("suggestion_id")
                                if pd.isna(sid) or not sid:
                                    continue
                                sid = int(sid)
                                orig = df[df["suggestion_id"] == sid]
                                if orig.empty:
                                    continue
                                orig = orig.iloc[0]
                                changed = any(
                                    str(row[c]) != str(orig[c])
                                    for c in ["suggested_email", "domain", "pattern"]
                                    if c in row
                                )
                                if changed:
                                    new_status = "MANUAL" if (
                                        row["suggested_email"] and
                                        str(row["suggested_email"]).strip() and
                                        orig["email_status"] in ("NOT_FOUND", None)
                                    ) else (orig["email_status"] or "FOUND")
                                    db.update_email_suggestion(
                                        conn, sid,
                                        str(row["suggested_email"]).strip(),
                                        str(row["domain"]).strip() if row.get("domain") else "",
                                        str(row["pattern"]).strip() if row.get("pattern") else "",
                                        new_status,
                                        confidence=1.0 if new_status == "MANUAL" else None,
                                    )
                                    count_up += 1
                            conn.commit()
                            conn.close()
                            if count_up:
                                st.success(f"{count_up} mise(s) à jour.")
                                st.rerun()
                            else:
                                st.info("Aucune modification.")

                    with col_del:
                        if st.button("🗑️ Tout supprimer", key="finder_del_all"):
                            st.session_state["finder_confirm_del"] = True

                        if st.session_state.get("finder_confirm_del"):
                            st.warning("⚠️ Supprimer toutes les suggestions ?")
                            cy, cn = st.columns(2)
                            with cy:
                                if st.button("✅ Oui", key="finder_del_yes"):
                                    conn = db.get_connection()
                                    db.delete_all_email_suggestions(conn)
                                    conn.commit()
                                    conn.close()
                                    st.session_state["finder_confirm_del"] = False
                                    st.success("Supprimé.")
                                    st.rerun()
                            with cn:
                                if st.button("❌ Non", key="finder_del_no"):
                                    st.session_state["finder_confirm_del"] = False
                                    st.rerun()

                    with col_export:
                        # Export CSV with emails
                        export_df = df[["firstname", "lastname", "company",
                                        "suggested_email", "domain", "confiance"]].copy()
                        export_df.columns = ["Prénom", "Nom", "Entreprise",
                                             "Email", "Domaine", "Confiance %"]
                        csv = df_to_csv_bytes(export_df)
                        st.download_button(
                            "📥 Exporter CSV",
                            data=csv,
                            file_name="prospects_emails.csv",
                            mime="text/csv",
                            width="stretch",
                        )

            else:
                st.info("Aucun prospect en base.")

        except Exception as e:
            st.error(str(e))


# =========================================================================
# TAB 3 : Saisie manuelle
# =========================================================================
with tab_manual:
    st.subheader("✏️ Prospects sans email")
    st.markdown("Saisissez manuellement l'email des prospects non trouvés.")

    try:
        conn = db.get_connection()
        missing = db.get_prospects_without_any_email(conn)
        conn.close()

        if not missing:
            st.markdown(
                '<div style="text-align:center;padding:2rem;">'
                '<div style="font-size:2.5rem;">🎉</div>'
                '<h3>Tous les prospects ont un email !</h3></div>',
                unsafe_allow_html=True,
            )
        else:
            df_miss = pd.DataFrame([dict(r) for r in missing])
            st.metric("📧 Sans email", len(df_miss))

            edit_cols = ["id", "firstname", "lastname", "company"]
            df_edit = df_miss[edit_cols].copy()
            df_edit["email_manual"] = ""

            edited = st.data_editor(
                df_edit,
                width="stretch",
                num_rows="fixed",
                disabled=["id", "firstname", "lastname", "company"],
                key="finder_manual_editor",
                hide_index=True,
                column_config={
                    "email_manual": st.column_config.TextColumn(
                        "📧 Email", width="large",
                    ),
                },
                height=400,
            )

            if st.button("💾 Sauvegarder", key="finder_manual_save", type="primary",
                          width="stretch"):
                conn = db.get_connection()
                count_saved = 0
                for _, row in edited.iterrows():
                    email_val = str(row.get("email_manual", "")).strip()
                    if email_val and "@" in email_val:
                        domain_val = email_val.split("@")[1]
                        pid = row["id"]
                        existing = conn.execute(
                            "SELECT id FROM email_suggestions WHERE prospect_id=?",
                            (pid,),
                        ).fetchone()
                        if existing:
                            db.update_email_suggestion(
                                conn, existing["id"], email_val, domain_val,
                                "manual", "MANUAL", confidence=1.0,
                            )
                        else:
                            db.upsert_email_suggestion(
                                conn, pid, domain_val, "manual",
                                email_val, 1.0, "MANUAL", "Saisie manuelle",
                            )
                        count_saved += 1
                conn.commit()
                conn.close()
                if count_saved:
                    st.success(f"✅ {count_saved} email(s) sauvegardé(s).")
                    st.rerun()
                else:
                    st.warning("Aucun email valide (format : nom@domaine.com)")

    except Exception as e:
        st.error(str(e))

# ── Gestion des prospects (en bas) ─────────────────────
st.markdown("---")
with st.expander("🗃️ Gérer les prospects en base"):
    conn = db.get_connection()
    rows = db.get_all_prospects(conn)
    conn.close()

    if not rows:
        st.info("Aucun prospect en base.")
    else:
        df_db = pd.DataFrame([dict(r) for r in rows])
        search_db = st.text_input("🔍 Rechercher", key="finder_search_db",
                                   placeholder="Nom, entreprise…")
        if search_db:
            mask = (
                df_db["firstname"].str.contains(search_db, case=False, na=False)
                | df_db["lastname"].str.contains(search_db, case=False, na=False)
                | df_db["company"].str.contains(search_db, case=False, na=False)
            )
            df_db = df_db[mask].copy()

        st.caption(f"{len(df_db)} prospect(s)")
        st.dataframe(
            df_db[["id", "firstname", "lastname", "company"]],
            width="stretch", height=300, hide_index=True,
        )

        if st.button("🗑️ Supprimer TOUS les prospects", key="finder_del_all_p",
                      type="primary"):
            st.session_state["finder_confirm_del_p"] = True

        if st.session_state.get("finder_confirm_del_p"):
            st.warning("⚠️ Cela supprimera **tous** les prospects et suggestions.")
            cy, cn = st.columns(2)
            with cy:
                if st.button("✅ Confirmer", key="finder_del_p_yes"):
                    conn = db.get_connection()
                    db.delete_all_prospects(conn)
                    conn.commit()
                    conn.close()
                    st.session_state["finder_confirm_del_p"] = False
                    st.rerun()
            with cn:
                if st.button("❌ Annuler", key="finder_del_p_no"):
                    st.session_state["finder_confirm_del_p"] = False
                    st.rerun()
