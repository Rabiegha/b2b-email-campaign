"""
Page 1 -- Import Data
Upload prospects (csv/xlsx) and messages (csv/xlsx) with auto-column detection.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.normalize import normalize_company
from engine.io_utils import read_upload, detect_prospect_columns, detect_message_columns, validate_mapping

st.set_page_config(page_title="Import Data", layout="wide")
st.title("1 -- Import Data")

# =========================================================================
# Prospects
# =========================================================================
st.header("Prospects")
st.markdown("Colonnes attendues : **firstname**, **lastname**, **company** (synonymes acceptes)")

file_p = st.file_uploader("Fichier prospects (CSV / XLSX)", type=["csv", "xlsx", "xls"], key="up_prospects")

if file_p is not None:
    df_p = read_upload(file_p)
    if df_p is None or df_p.empty:
        st.error("Impossible de lire le fichier prospects.")
    else:
        mapping_p = detect_prospect_columns(df_p)
        missing_p = validate_mapping(mapping_p)

        st.markdown("**Colonnes detectees :**")
        for canon, orig in mapping_p.items():
            if orig:
                st.write(f"  - {canon} -> `{orig}`")
            else:
                st.warning(f"  - {canon} : non trouve !")

        if missing_p:
            st.error(f"Colonnes manquantes : {', '.join(missing_p)}. Verifiez votre fichier.")
        else:
            st.markdown("**Apercu (20 premieres lignes) :**")
            st.dataframe(df_p.head(20), use_container_width=True)

            if st.button("Importer prospects dans la DB", key="btn_import_p"):
                conn = db.get_connection()
                count = 0
                for _, row in df_p.iterrows():
                    fn = str(row[mapping_p["firstname"]]).strip()
                    ln = str(row[mapping_p["lastname"]]).strip()
                    co = str(row[mapping_p["company"]]).strip()
                    if fn and ln and co:
                        ck = normalize_company(co)
                        db.insert_prospect(conn, fn, ln, co, ck)
                        count += 1
                conn.commit()
                conn.close()
                st.success(f"{count} prospects importes.")

st.markdown("---")

# =========================================================================
# Messages
# =========================================================================
st.header("Messages")
st.markdown("Colonnes attendues : **company**, **subject**, **body_text** (synonymes acceptes)")

file_m = st.file_uploader("Fichier messages (CSV / XLSX)", type=["csv", "xlsx", "xls"], key="up_messages")

if file_m is not None:
    df_m = read_upload(file_m)
    if df_m is None or df_m.empty:
        st.error("Impossible de lire le fichier messages.")
    else:
        mapping_m = detect_message_columns(df_m)
        missing_m = validate_mapping(mapping_m)

        st.markdown("**Colonnes detectees :**")
        for canon, orig in mapping_m.items():
            if orig:
                st.write(f"  - {canon} -> `{orig}`")
            else:
                st.warning(f"  - {canon} : non trouve !")

        if missing_m:
            st.error(f"Colonnes manquantes : {', '.join(missing_m)}. Verifiez votre fichier.")
        else:
            st.markdown("**Apercu (20 premieres lignes) :**")
            st.dataframe(df_m.head(20), use_container_width=True)

            if st.button("Importer messages dans la DB", key="btn_import_m"):
                conn = db.get_connection()
                count = 0
                for _, row in df_m.iterrows():
                    co = str(row[mapping_m["company"]]).strip()
                    subj = str(row[mapping_m["subject"]]).strip()
                    body = str(row[mapping_m["body_text"]]).strip()
                    if co and subj:
                        ck = normalize_company(co)
                        db.insert_message(conn, co, ck, subj, body)
                        count += 1
                conn.commit()
                conn.close()
                st.success(f"{count} messages importes.")

st.markdown("---")

# =========================================================================
# Current DB counts
# =========================================================================
st.header("Etat de la base")
try:
    conn = db.get_connection()
    n_p = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    n_m = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    c1, c2 = st.columns(2)
    c1.metric("Prospects en base", n_p)
    c2.metric("Messages en base", n_m)
except Exception as e:
    st.error(str(e))
