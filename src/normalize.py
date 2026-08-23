"""
normalize.py
-------------
Turns messy strings into approved-vocabulary strings, without any
transformer model - just regex, fuzzy string matching (rapidfuzz, classic
edit-distance) and lookup tables.

Important finding from inspecting the real sample data: `Part_Manuf`
("Appliance Dealers Cooperative (APPDE)") is frequently a *distributor/
vendor account name*, not the true OEM manufacturer ("Rheem Manufacturing"
/ "FRIGIDAIRE(R)" in the ground-truth row for that exact item). So this
module treats Part_Manuf as one weak candidate signal among several,
never as ground truth by itself - matching the guide's own warning that
"the manufacturer and brand look mismatched" in real rows.

Resolution order for MANUFACTURER_NAME / BRAND_NAME:
  1. self-learning cache (a human already resolved this exact string)
  2. official UniCat_Manufacturer_and_Brand_List.xlsx, if present in data/
     -> fuzzy match against Part_Manuf, brand-token, and discovered domain
  3. the domain/site-name discovered by the web-search step (search_engine.py)
     -> most reliable *when the pipeline has live internet*, because the
        manufacturer's own site literally names itself
  4. cleaned Part_Manuf string, flagged LOW confidence, routed to review

Everything here is deterministic and inspectable - good for an audit trail,
bad at "guessing" - which is the correct trade-off for a controlled-
vocabulary field per the guide ("a fluent description of invented values
scores zero").
"""
import os
import re
import functools
import pandas as pd
from rapidfuzz import fuzz, process

from . import config

_MANUF_CODE_RE = re.compile(r"^(.*?)\s*\(([A-Za-z0-9]+)\)\s*$")

SEED_BRANDS = {
    "3m": ("3M Company", "3M"),
    "3m company": ("3M Company", "3M"),
    "stikit": ("3M Company", "3M"),
    "cubitron": ("3M Company", "3M"),
    "scotch": ("3M Company", "Scotch"),
    "dewalt": ("Stanley Black & Decker", "DeWALT"),
    "milwaukee": ("Milwaukee Tool", "Milwaukee"),
    "diablo": ("Freud Inc", "Diablo"),
    "freud": ("Freud Inc", "Freud"),
    "mirka": ("Mirka Abrasives Inc", "Mirka"),
    "abranet": ("Mirka Abrasives Inc", "Mirka"),
    "hiolit": ("Mirka Abrasives Inc", "Mirka"),
    "whirlpool": ("Whirlpool Corporation", "Whirlpool"),
    "frigidaire": ("Electrolux (Frigidaire)", "Frigidaire"),
    "makita": ("Makita Corporation", "Makita"),
    "bosch": ("Robert Bosch Tool Corporation", "Bosch"),
    "festool": ("Festool USA", "Festool"),
    "norton": ("Saint-Gobain Abrasives", "Norton"),
    "kichler": ("Kichler Lighting", "Kichler"),
    "delta": ("Delta Faucet Company", "Delta"),
    "moen": ("Moen Incorporated", "Moen"),
    "kohler": ("Kohler Co", "Kohler"),
    "rheem": ("Rheem Manufacturing", "Rheem"),
    "ge": ("GE Appliances", "GE"),
    "lg": ("LG Electronics", "LG"),
    "samsung": ("Samsung Electronics", "Samsung"),
    "black+decker": ("Stanley Black & Decker", "Black+Decker"),
    "black & decker": ("Stanley Black & Decker", "Black+Decker"),
    "stanley": ("Stanley Black & Decker", "Stanley"),
    "ridgid": ("Ridge Tool Company (RIDGID)", "RIDGID"),
    "irwin": ("Stanley Black & Decker", "IRWIN Tools"),
    "honeywell": ("Honeywell International", "Honeywell"),
    "philips": ("Signify (Philips)", "Philips"),
    "sunmight": ("Sunmight USA", "Sunmight"),
}


def parse_manuf_field(part_manuf: str):
    """'Appliance Dealers Cooperative (APPDE)' -> ('Appliance Dealers Cooperative', 'APPDE')"""
    if not part_manuf:
        return "", ""
    m = _MANUF_CODE_RE.match(part_manuf.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return part_manuf.strip(), ""


@functools.lru_cache(maxsize=1)
def _load_master_list():
    path = os.path.join(config.DATA_DIR, config.OPTIONAL_REFERENCE_FILES["manufacturer_brand_list"])
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path, dtype=str).fillna("")
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception:
        return None


def _fuzzy_master_lookup(candidate: str, min_score=80):
    df = _load_master_list()
    if df is None or not candidate:
        return None
    if candidate.strip().lower() in config.BLOCKED_BRAND_NAMES:
        return None
    col = "MANUFACTURER_NAME" if "MANUFACTURER_NAME" in df.columns else df.columns[0]
    choices = df[col].tolist()
    match = process.extractOne(candidate, choices, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= min_score:
        row = df.iloc[match[2]]
        return {
            "manufacturer_name": row.get("MANUFACTURER_NAME", candidate),
            "brand_name": row.get("BRAND_NAME", ""),
            "confidence": match[1] / 100.0,
            "source": "master_list",
        }
    return None


def domain_to_brand_guess(domain: str) -> str:
    """'www.frigidaire.com' -> 'Frigidaire' - last-resort brand guess from a URL."""
    if not domain:
        return ""
    host = re.sub(r"^https?://", "", domain).split("/")[0]
    host = re.sub(r"^www\d*\.", "", host).lower()
    for b in config.BLOCKED_DOMAINS:
        if host == b or host.endswith("." + b) or b in host:
            return ""
    core = host.split(".")[0]
    core = re.sub(r"[-_]", " ", core)
    guess = core.strip().title()
    if guess.lower() in config.BLOCKED_BRAND_NAMES:
        return ""
    return guess


def resolve_manufacturer_brand(part_manuf: str, part_desc: str = "", part_num: str = "",
                                discovered_domain: str = "", discovered_site_name: str = ""):
    """
    Returns dict: manufacturer_name, brand_name, confidence (0-1), source
    Tries part-family cache -> description/manuf seed matching -> master list -> discovered web identity -> raw fallback.
    """
    from . import cache_store

    raw_name, _code = parse_manuf_field(part_manuf)

    if part_num:
        hit = cache_store.get_manufacturer_for_part(part_num)
        if hit and hit.get("manufacturer_name"):
            mfr = hit.get("manufacturer_name", "")
            if mfr.lower() not in config.BLOCKED_BRAND_NAMES:
                return {**hit, "confidence": 0.98, "source": "human_cache"}

    desc_words = (part_desc or "").split()
    desc_first_2 = desc_words[:3]
    candidate_tokens = []
    if raw_name:
        candidate_tokens.append(raw_name)
        candidate_tokens.append(raw_name.split()[0])
    for w in desc_first_2:
        candidate_tokens.append(w.strip("-,:;\"'"))

    for tok in candidate_tokens:
        tok_clean = tok.strip().lower()
        if tok_clean in SEED_BRANDS:
            mfr, brnd = SEED_BRANDS[tok_clean]
            return {
                "manufacturer_name": mfr,
                "brand_name": brnd,
                "confidence": 0.92,
                "source": "seed_match"
            }

    for key in (discovered_site_name, discovered_domain):
        if key and key.strip().lower() not in config.BLOCKED_BRAND_NAMES:
            hit = cache_store.get_manufacturer_alias(key)
            if hit and hit.get("manufacturer_name") and hit.get("manufacturer_name").lower() not in config.BLOCKED_BRAND_NAMES:
                return {**hit, "confidence": 0.9, "source": "brand_string_cache"}

    for candidate in (raw_name, discovered_site_name):
        if candidate and candidate.strip().lower() not in config.BLOCKED_BRAND_NAMES:
            hit = _fuzzy_master_lookup(candidate)
            if hit:
                return hit

    clean_site_name = discovered_site_name.strip()
    if clean_site_name and clean_site_name.lower() not in config.BLOCKED_BRAND_NAMES:
        tok_low = clean_site_name.lower()
        if tok_low in SEED_BRANDS:
            mfr, brnd = SEED_BRANDS[tok_low]
            return {"manufacturer_name": mfr, "brand_name": brnd, "confidence": 0.85, "source": "web_discovery"}
        return {
            "manufacturer_name": clean_site_name,
            "brand_name": clean_site_name,
            "confidence": 0.60,
            "source": "web_discovery",
        }

    if discovered_domain:
        guess = domain_to_brand_guess(discovered_domain)
        if guess and guess.lower() not in config.BLOCKED_BRAND_NAMES:
            tok_low = guess.lower()
            if tok_low in SEED_BRANDS:
                mfr, brnd = SEED_BRANDS[tok_low]
                return {"manufacturer_name": mfr, "brand_name": brnd, "confidence": 0.75, "source": "domain_guess"}
            return {
                "manufacturer_name": guess,
                "brand_name": guess,
                "confidence": 0.45,
                "source": "domain_guess",
            }

    if raw_name and raw_name.lower() not in config.BLOCKED_BRAND_NAMES:
        clean_raw = re.sub(r"\b(Inc|LLC|Corp|Corporation|Co|Company|Ltd)\b\.?", "", raw_name, flags=re.IGNORECASE).strip()
        return {
            "manufacturer_name": raw_name,
            "brand_name": clean_raw or raw_name,
            "confidence": 0.4,
            "source": "raw_fallback"
        }

    return {"manufacturer_name": "", "brand_name": "", "confidence": 0.0, "source": "none"}


@functools.lru_cache(maxsize=1)
def _load_official_uom_map():
    path = os.path.join(config.DATA_DIR, config.OPTIONAL_REFERENCE_FILES["uom_standards"])
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_excel(path, sheet_name=0, dtype=str).fillna("")
        df.columns = [c.strip().lower() for c in df.columns]
        raw_col = next((c for c in df.columns if "abbrev" not in c and ("unit" in c or "term" in c)), df.columns[0])
        abbr_col = next((c for c in df.columns if "abbrev" in c), df.columns[-1])
        m = {}
        for _, row in df.iterrows():
            raw, abbr = row.get(raw_col, "").strip().lower(), row.get(abbr_col, "").strip()
            if raw and abbr:
                m[raw] = abbr
        return m
    except Exception:
        return {}


def normalize_uom(unit_text: str) -> str:
    if not unit_text:
        return ""
    key = unit_text.strip().lower().rstrip(".")
    official = _load_official_uom_map()
    if key in official:
        return official[key]
    if key in config.DEFAULT_UOM_MAP:
        return config.DEFAULT_UOM_MAP[key]
    if key in config.UNIT_TOKENS_LOWER:
        return config.UNIT_TOKENS_LOWER[key]
    return unit_text.strip()


def format_number_unit(number: str, unit: str) -> str:
    """Guide's house rule: always a space between number and unit."""
    unit = normalize_uom(unit)
    number = str(number).strip()
    return f"{number} {unit}".strip() if unit else number


def decimal_to_fraction_inch(value: float) -> str:
    """0.5 -> '1/2', 50.25 -> '50-1/4' (guide's worked example)."""
    whole = int(value)
    frac = round(value - whole, 6)
    if frac == 0:
        return str(whole)
    frac_str = config.FRACTION_TABLE.get(round(frac, 6))
    if not frac_str:
        nearest = min(config.FRACTION_TABLE.keys(), key=lambda k: abs(k - frac))
        frac_str = config.FRACTION_TABLE[nearest]
    return f"{whole}-{frac_str}" if whole else frac_str
