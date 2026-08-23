"""
describe.py
------------
Builds the five description formats the guide's worked example shows
(same facts, rewritten five ways). This is pure string templating - no
model, generative or otherwise - so every character in the output traces
back to a specific extracted field.

Formulas are reverse-engineered from the ONE worked example in the guide
(FRIGIDAIRE PDSH4816AF) since UNILOG_INTERNAL_CONTENT_GUIDELINES.docx
(the actual formula spec) wasn't supplied. If that file is added to
data/, a tighter implementation should read its per-field formula/char-
limit table instead of these defaults - the function signatures here are
written so that swap is a drop-in (replace the constants at the top,
logic stays the same).
"""
import re
from . import config

INVOICE_DESC_MAX = 40
MOBILE_DESC_RANGE = (60, 80)

WORD_ABBREV = {
    "stainless steel": "SST", "galvanized": "GALV", "professional": "PRO",
    "mounting": "MTG", "installation": "INSTL", "dishwasher": "DISHWASHER",
    "with": "W/", "without": "W/O", "inch": "IN", "inches": "IN",
    "gallon": "GAL", "gallons": "GAL", "diameter": "DIA",
}


def _abbrev(word: str) -> str:
    return WORD_ABBREV.get(word.lower(), word)


def _title_case_preserve_marks(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _dedupe_preserve_order(items):
    seen, out = set(), []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            out.append(item)
            seen.add(key)
    return out


def build_invoice_desc(product_name, attributes: dict, max_len=INVOICE_DESC_MAX):
    """
    ALL CAPS, <=40 chars, tightly packed: item type + the most identifying
    attributes (mounting, cycles/qty, material, voltage, amperage, a size/
    depth figure) - matches "DISHWASHER LEG 5 SST 120V 15A 50-1/4IN".
    Attributes are added in priority order and dropped from the end if
    the line would exceed max_len, so it degrades gracefully rather than
    hard-truncating mid-word.
    """
    parts = [product_name] if product_name else []
    priority = ["Mounting Type", "Number of Wash Cycles", "Material",
                "Voltage Rating", "Amperage Rating", "Depth", "Depth With Door Open",
                "Length", "Width", "Height", "Diameter"]
    for label in priority:
        if label not in attributes:
            continue
        val, unit = attributes[label]
        val = _abbrev(val)
        token = f"{val}{unit}" if unit and label in ("Voltage Rating", "Amperage Rating") else \
                (f"{val}{unit}" if unit else val)
        parts.append(token)

    line = " ".join(p for p in parts if p).upper()
    while len(line) > max_len and len(parts) > 1:
        parts.pop()
        line = " ".join(p for p in parts if p).upper()
    return line[:max_len].strip()


def _clean_brand(b: str) -> str:
    if not b:
        return ""
    b_clean = b.strip()
    if b_clean.lower() in config.BLOCKED_BRAND_NAMES:
        return ""
    return b_clean


def build_mobile_desc(manufacturer_name, brand_name, product_name, series, mpn):
    """60-80 char target: 'Manufacturer Brand, ItemType, Series, MPN'."""
    mfr = _clean_brand(manufacturer_name)
    brnd = _clean_brand(brand_name)
    if mfr and brnd and mfr.lower() == brnd.lower():
        bits = [mfr]
    else:
        bits = [b for b in (mfr, brnd) if b]
    head = " ".join(bits)
    tail_bits = [b for b in (product_name, series, mpn) if b]
    desc = f"{head}, " + ", ".join(tail_bits) if head else ", ".join(tail_bits)
    desc = _title_case_preserve_marks(desc)
    lo, hi = MOBILE_DESC_RANGE
    if len(desc) > hi:
        desc = desc[:hi].rsplit(",", 1)[0]
    return desc


def build_short_desc(brand_name, series, mpn, product_name, with_feature, attributes: dict,
                      max_attrs=3):
    """
    Product title: 'Brand Series MPN ItemType With Feature, attr1, attr2, attr3'
    """
    brnd = _clean_brand(brand_name)
    head = " ".join(b for b in (brnd, series, mpn, product_name) if b)
    if with_feature:
        head += f" With {with_feature}"
    tail = []
    picked = 0
    for label in ("Mounting Type", "Number of Wash Cycles", "Material", "Color"):
        if label in attributes and picked < max_attrs:
            val, unit = attributes[label]
            if label == "Number of Wash Cycles":
                tail.append(f"{val}-Wash Cycle")
            elif label == "Mounting Type":
                tail.append(f"{val} Mounting")
            else:
                tail.append(val)
            picked += 1
    desc = head + (", " + ", ".join(_dedupe_preserve_order(tail)) if tail else "")
    return _title_case_preserve_marks(desc)


def build_long_desc(brand_name, product_name, with_feature, series, attributes: dict):
    """Fuller sentence: brand + item type + feature + comma-separated key specs."""
    brnd = _clean_brand(brand_name)
    head_bits = [b for b in (brnd, product_name) if b]
    head = " ".join(head_bits)
    if with_feature:
        head += f" With {with_feature}"
    tail = []
    if series:
        tail.append(series)
    label_order = ["Number of Wash Cycles", "Voltage Rating", "Amperage Rating",
                   "Mounting Type", "Length", "Width", "Height", "Depth",
                   "Depth With Door Open", "Sound Level", "Material", "Color"]
    for label in label_order:
        if label not in attributes:
            continue
        val, unit = attributes[label]
        if label == "Number of Wash Cycles":
            tail.append(f"{val} Wash Cycles")
        elif label in ("Voltage Rating",):
            tail.append(f"{val} {unit}".strip())
        elif label in ("Amperage Rating",):
            tail.append(f"{val} {unit}".strip())
        elif label in ("Depth", "Depth With Door Open", "Length", "Width", "Height"):
            tail.append(f"{val} {unit} {label}".strip())
        elif label == "Sound Level":
            tail.append(f"{val} {unit} Sound Level".strip())
        else:
            tail.append(val)
    desc = head + (", " + ", ".join(_dedupe_preserve_order(tail)) if tail else "")
    return _title_case_preserve_marks(desc)


def build_retail_desc(series, product_name, attributes: dict):
    """Shortest, no brand/MPN: 'Series ItemType, Mounting, N-Wash Cycle, Material'."""
    head = " ".join(b for b in (series, product_name) if b)
    tail = []
    if "Mounting Type" in attributes:
        tail.append(f"{attributes['Mounting Type'][0]} Mounting")
    if "Number of Wash Cycles" in attributes:
        tail.append(f"{attributes['Number of Wash Cycles'][0]}-Wash Cycle")
    if "Material" in attributes:
        tail.append(attributes["Material"][0])
    desc = head + (", " + ", ".join(tail) if tail else "")
    return _title_case_preserve_marks(desc)
