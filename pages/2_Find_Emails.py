"""
Page 2 -- Find Emails
Find domain, infer email pattern, and generate suggested email for each prospect.
"""

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import db
from engine.domain_finder import find_domain
from engine.web_discovery import discover_emails
from engine.email_pattern import infer_pattern, generate_email
from engine.io_utils import rows_to_dataframe

st.set_page_config(page_title="Find Emails", layout="wide")
st.title("2 -- Find Emails")

# Parameters
st.markdown("### Parametres")
col1, col2 = st.columns(2)
with col1:
    max_prospects = st.number_input("Max prospects a traiter (0 = tous)", min_value=0, value=0, step=10)
with col2:
    force_refresh = st.checkbox("Forcer le refresh du cache", value=False)

# Run button
if st.button("Lancer la recherche d'emails"):
    conn = db.get_connection()

    if max_prospects > 0:
        if force_refresh:
            prospects = db.get_all_prospects_for_find(conn, limit=max_prospects)
        else:
            prospects = db.get_prospects_without_suggestion(conn, limit=max_prospects)
    else:
        if force_refresh:
            prospects = db.get_all_prospects_for_find(conn)
        else:
            prospects = db.get_prospects_without_suggestion(conn)

    total = len(prospects)
    if total == 0:
        st.info("Aucun prospect a traiter. Tous ont deja une suggestion, ou la base est vide.")
    else:
        progress = st.progress(0, text="Recherche en cours...")
        status_area = st.empty()

        # Group by company_key to avoid redundant lookups
        company_groups: dict[str, list] = {}
        for p in prospects:
            ck = p["company_key"]
            if ck not in company_groups:
                company_groups[ck] = []
            company_groups[ck].append(p)

        processed = 0
        for ck, group in company_groups.items():
            company = group[0]["company"]
            status_area.text(f"Traitement: {company} ({processed}/{total})")

            # 1) Find domain
            domain = find_domain(company, force_refresh=force_refresh)

            if not domain:
                # No domain found
                for p in group:
                    db.upsert_email_suggestion(
                        conn, p["id"], None, None, None, 0.0,
                        "NOT_FOUND", "Domaine non trouve"
                    )
                    processed += 1
                    progress.progress(processed / total)
                conn.commit()
                continue

            # 2) Discover emails on domain
            found_emails = discover_emails(domain)

            # 3) Infer pattern
            pattern, confidence, debug = infer_pattern(domain, found_emails, force_refresh=force_refresh)

            # 4) Generate email for each prospect
            for p in group:
                suggested = generate_email(p["firstname"], p["lastname"], domain, pattern)
                status = "FOUND" if suggested else "NOT_FOUND"
                notes = f"domain={domain}, pattern={pattern}, {debug}"

                db.upsert_email_suggestion(
                    conn, p["id"], domain, pattern, suggested,
                    confidence, status, notes
                )
                processed += 1
                progress.progress(processed / total)

            conn.commit()

        progress.progress(1.0, text="Termine !")
        status_area.text(f"Termine : {total} prospects traites.")
        conn.close()

st.markdown("---")

# Show current suggestions
st.header("Suggestions actuelles")
try:
    conn = db.get_connection()
    suggestions = db.get_email_suggestions(conn)
    conn.close()

    if suggestions:
        df = rows_to_dataframe(suggestions)
        display_cols = ["firstname", "lastname", "company", "suggested_email",
                        "confidence_score", "status", "domain", "pattern", "debug_notes"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], use_container_width=True, height=500)
        st.metric("Total suggestions", len(df))
    else:
        st.info("Aucune suggestion pour le moment.")
except Exception as e:
    st.error(str(e))
