"""
Normalisation utilities for company names and person names.
"""

import re
import unicodedata

# Legal suffixes to strip (French + international)
LEGAL_FORMS = {
    "sas", "sasu", "sarl", "eurl", "sa", "sci", "snc", "sccv",
    "selarl", "selas", "gmbh", "ltd", "llc", "inc", "bv", "nv",
    "spa", "plc", "ag", "co", "corp",
}


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def normalize_company(name: str) -> str:
    """
    Normalise a company name for matching:
    lowercase, strip accents, replace & -> et, remove punctuation,
    remove legal forms, collapse whitespace.
    """
    if not name:
        return ""
    s = name.lower().strip()
    s = _strip_accents(s)
    s = s.replace("&", " et ")
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = s.split()
    tokens = [t for t in tokens if t not in LEGAL_FORMS]
    return " ".join(tokens).strip()


def normalize_name_part(name: str) -> str:
    """
    Normalise a first/last name for email building:
    lowercase, strip accents, remove spaces & hyphens.
    Returns a single clean slug.
    """
    if not name:
        return ""
    s = name.lower().strip()
    s = _strip_accents(s)
    s = re.sub(r"[\s\-]+", "", s)
    s = re.sub(r"[^\w]", "", s)
    return s


def name_variants(name: str):
    """
    Return name variants: full slug + first-letter only.
    e.g. 'Jean-Pierre' -> ['jeanpierre', 'j']
    """
    slug = normalize_name_part(name)
    if not slug:
        return []
    return [slug, slug[0]]


def company_to_slug(name: str) -> str:
    """
    Convert company name to a slug suitable for domain guessing.
    'Acme Corp' -> 'acmecorp'
    """
    key = normalize_company(name)
    return re.sub(r"\s+", "", key)
