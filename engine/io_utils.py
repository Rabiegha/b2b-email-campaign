"""
I/O utilities: CSV/XLSX import with auto-detection of column synonyms,
and CSV export.
"""

import io
import logging
import pandas as pd

logger = logging.getLogger("b2b.io_utils")

# Column synonyms for auto-detection
PROSPECT_SYNONYMS = {
    "firstname": ["firstname", "prenom", "first_name", "prénom", "first"],
    "lastname": ["lastname", "nom", "last_name", "family_name", "last", "nom_de_famille"],
    "company": ["company", "entreprise", "societe", "société", "organization", "organisation", "compagnie"],
}

# Extended prospect synonyms (with optional email column for direct-send mode)
PROSPECT_WITH_EMAIL_SYNONYMS = {
    "firstname": ["firstname", "prenom", "first_name", "prénom", "first"],
    "lastname": ["lastname", "nom", "last_name", "family_name", "last", "nom_de_famille"],
    "company": ["company", "entreprise", "societe", "société", "organization", "organisation", "compagnie"],
    "email": ["email", "e-mail", "mail", "adresse_email", "adresse_mail",
              "email_address", "courriel", "adresse"],
}

MESSAGE_SYNONYMS = {
    "company": ["company", "entreprise", "societe", "société", "organization", "organisation", "compagnie"],
    "subject": ["subject", "objet", "sujet", "titre", "title"],
    "body_text": ["body_text", "message", "body", "content", "contenu", "texte", "corps"],
}


def _detect_column(df_columns: list[str], synonyms: list[str]) -> str | None:
    """
    Find the first column in df that matches one of the synonyms (case-insensitive).
    Returns the original column name or None.
    """
    lower_map = {c.lower().strip(): c for c in df_columns}
    for syn in synonyms:
        if syn.lower() in lower_map:
            return lower_map[syn.lower()]
    return None


def read_upload(uploaded_file) -> pd.DataFrame | None:
    """
    Read an uploaded file (CSV or XLSX) into a DataFrame.
    Returns None on error.
    """
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            # Try multiple encodings
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc)
                    return df
                except UnicodeDecodeError:
                    continue
            return None
        elif name.endswith((".xlsx", ".xls")):
            uploaded_file.seek(0)
            df = pd.read_excel(uploaded_file, engine="openpyxl")
            return df
        else:
            logger.warning("Unsupported file type: %s", name)
            return None
    except Exception as e:
        logger.error("Error reading file: %s", e)
        return None


def detect_prospect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Auto-detect prospect column mapping.
    Returns {canonical_name: original_column_name_or_None}.
    """
    cols = list(df.columns)
    return {
        "firstname": _detect_column(cols, PROSPECT_SYNONYMS["firstname"]),
        "lastname": _detect_column(cols, PROSPECT_SYNONYMS["lastname"]),
        "company": _detect_column(cols, PROSPECT_SYNONYMS["company"]),
    }


def detect_prospect_with_email_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Auto-detect prospect column mapping WITH optional email column.
    Returns {canonical_name: original_column_name_or_None}.
    """
    cols = list(df.columns)
    return {
        "firstname": _detect_column(cols, PROSPECT_WITH_EMAIL_SYNONYMS["firstname"]),
        "lastname": _detect_column(cols, PROSPECT_WITH_EMAIL_SYNONYMS["lastname"]),
        "company": _detect_column(cols, PROSPECT_WITH_EMAIL_SYNONYMS["company"]),
        "email": _detect_column(cols, PROSPECT_WITH_EMAIL_SYNONYMS["email"]),
    }


def detect_message_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Auto-detect message column mapping.
    Returns {canonical_name: original_column_name_or_None}.
    """
    cols = list(df.columns)
    return {
        "company": _detect_column(cols, MESSAGE_SYNONYMS["company"]),
        "subject": _detect_column(cols, MESSAGE_SYNONYMS["subject"]),
        "body_text": _detect_column(cols, MESSAGE_SYNONYMS["body_text"]),
    }


def validate_mapping(mapping: dict[str, str | None]) -> list[str]:
    """
    Returns list of missing required columns.
    """
    return [k for k, v in mapping.items() if v is None]


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convert DataFrame to CSV bytes for download."""
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def rows_to_dataframe(rows: list) -> pd.DataFrame:
    """Convert list of sqlite3.Row to DataFrame."""
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])
