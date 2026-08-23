"""
extract.py
-----------
The "retrieval + extraction" half of the RAG-like system. For each
attribute in config.ATTRIBUTE_QUERIES:
  1. Query the part's knowledge base with the attribute's synonyms.
     kb_index.PartKB.search() now blends BM25 + TF-IDF cosine similarity
     so synonym mismatches ("Noise" vs "Sound Level") no longer cause
     missed extractions — see kb_index.py for details.
  2. Look at the top-ranked chunks (combined score gives *candidates*,
     not ground truth - extract.py validates with regex, not ranking alone)
  3. Try to pull a value out with regex:
       a. "Label: value" / "Label - value" pattern (highest confidence -
          the source literally names the field)
       b. number-immediately-followed-by-known-unit pattern near a
          synonym keyword (medium confidence)
  4. Score confidence from: pattern type + BM25/TF-IDF rank + source
     trust tier (see search_engine.trust_score) + whether >1 source agrees

No transformer model anywhere in this file - just compiled regexes and
arithmetic. Any field extract_attribute() can't support with reasonable
confidence is left blank rather than guessed, per the guide's rule that
"a fluent description of invented values scores zero" - and instead
gets routed to the Streamlit review queue.
"""
import re
from dataclasses import dataclass

from . import config, normalize


@dataclass
class Extraction:
    label: str
    value: str
    unit: str
    confidence: float
    source_url: str
    snippet: str
    agreement_count: int = 1


_UNIT_ALT = "|".join(re.escape(u) for u in config.UNIT_TOKENS)

_NUM_FRAGMENT = r"(?:\d+-\d+/\d+|\d+/\d+|\d+\.\d+|\d+)"

_NUM_UNIT_RE = re.compile(
    r"(" + _NUM_FRAGMENT + r")\s?(" + _UNIT_ALT + r")\b"
)


NOISE_PROSE_PATTERNS = [
    r"--- \.", r"\+\+\+ \.", r"@@ -\d+", r"\bdiff --git\b", r"\bfiles? changed\b",
    r"\binsertions?\(\+\)", r"\bcreate mode \d+", r"\bcommit [0-9a-f]{7,40}\b",
    r"\bFrom: \b", r"\bMerge branch\b", r"\.gitignore\b", r"\.patch\b",
    r"\brobot or human\b", r"\bactivate and hold\b", r"\bconfirm that you[’']re human\b",
    r"\bjavascript is required\b", r"\benable javascript\b", r"\brecaptcha\b", r"\bcloudflare\b",
    r"\bdescargar\b", r"\bguardar para m[aá]s tarde\b", r"\bmarcar este documento\b",
    r"\bfound this document useful\b", r"\bsave for later\b", r"\bprivacy policy\b",
    r"\bterms of (service|use)\b", r"\bcopyright\b", r"\ball rights reserved\b",
    r"\bmrp tag\b", r"\bregular price\b", r"\bmost read\b", r"\bactors build\b",
    r"\bgithub\b", r"\bscribd\b", r"\bmanualslib\b", r"\bslideshare\b", r"\bwalmart\b",
]
_NOISE_PROSE_RE = re.compile("|".join(NOISE_PROSE_PATTERNS), re.IGNORECASE)


def is_clean_text(s: str) -> bool:
    if not s or len(s.strip()) < 2:
        return False
    if _NOISE_PROSE_RE.search(s):
        return False
    ascii_count = sum(1 for c in s if ord(c) < 128)
    if (ascii_count / len(s)) < 0.80:
        return False
    return True


def _find_label_value(text: str, synonyms: list):
    """
    Line-anchored "Label: Value" / "Label - Value" matcher. The synonym
    must own the *start* of the line (a bullet marker is tolerated) and
    be immediately followed by a colon or dash.
    """
    lines = text.splitlines()
    for syn in sorted(synonyms, key=len, reverse=True):
        pattern = re.compile(r"^\s*[\-\*\u2022]?\s*" + re.escape(syn) + r"\s*[:\-]\s*(.+?)\s*$",
                              re.IGNORECASE)
        for line in lines:
            m = pattern.match(line)
            if m:
                val = m.group(1).strip().rstrip(".,;")
                if val and is_clean_text(val) and len(val) <= 80:
                    return val
    return None


def find_label_value(text: str, synonyms: list):
    """
    Public wrapper for one-off "Label: Value" lookups on a full document's
    plain text (warranty statement, country of origin), used outside the
    per-attribute BM25-retrieval flow in extract_attribute().
    """
    return _find_label_value(text, synonyms)


def _find_number_unit_near(text: str, synonyms: list, allowed_units: list, window: int = 40):
    """Find a number+unit token that appears within `window` chars of a synonym keyword."""
    low = text.lower()
    for syn in synonyms:
        idx = low.find(syn.lower())
        if idx == -1:
            continue
        span = text[max(0, idx - window): idx + len(syn) + window]
        for m in _NUM_UNIT_RE.finditer(span):
            num, unit = m.group(1), m.group(2)
            if not allowed_units or unit in allowed_units or unit.upper() in [u.upper() for u in allowed_units]:
                return num, unit
    return None


def extract_attribute(kb, label: str, spec: dict, top_k: int = 5, domain_trust=None):
    """
    kb: kb_index.PartKB
    spec: config.ATTRIBUTE_QUERIES[label]  ({"synonyms": [...], "units": [...]})
    domain_trust: optional callable(url) -> float, defaults to search_engine.trust_score
    Returns Extraction or None.

    Cross-source agreement: when a part's knowledge base has multiple
    documents (the manufacturer page AND a spec sheet AND a manual - which
    the pipeline already fetches for other reasons, so checking agreement
    here costs no extra network calls), the SAME value showing up from
    independent chunks is a much stronger signal than any single match,
    however well-ranked. This collects every candidate across the top-k
    chunks, groups them by normalized value, and any value confirmed by
    2+ DISTINCT source URLs gets a confidence bonus - proportionally more
    for 3 agreeing sources than 2. A single unconfirmed match still wins
    if nothing else was found; it just won't outscore a corroborated one
    from a lower-ranked chunk.

    Update (2026-08): top_k raised from 4→5 to give the TF-IDF retriever
    (kb_index) more candidates to surface semantic matches. The src_conf
    formula now uses the full [0,1] trust_score range (trust_score was
    capped at 0.55 before the search_engine fix; it now reaches 0.90 for
    manufacturer PDFs), so base_confidence properly reflects source quality.
    """
    if domain_trust is None:
        from .search_engine import trust_score as domain_trust

    query = label + " " + " ".join(spec["synonyms"])
    candidates = kb.search(query, top_k=top_k)
    if not candidates:
        return None

    found = []
    for rank, (chunk, combined_score) in enumerate(candidates):
        label_val = _find_label_value(chunk.text, spec["synonyms"] + [label])
        num_unit = None
        if not label_val:
            num_unit = _find_number_unit_near(chunk.text, spec["synonyms"] + [label], spec["units"])

        if not label_val and not num_unit:
            continue

        if label_val:
            m = _NUM_UNIT_RE.search(label_val)
            if m and spec["units"]:
                value, unit = m.group(1), normalize.normalize_uom(m.group(2))
            else:
                value, unit = label_val, ""
            pattern_conf = 0.90
        else:
            value, unit = num_unit[0], normalize.normalize_uom(num_unit[1])
            pattern_conf = 0.68

        rank_conf = float(combined_score) if combined_score > 0 else max(0.3, 1.0 - rank * 0.15)
        src_conf = max(0.25, domain_trust(chunk.source_url))
        base_confidence = pattern_conf * 0.50 + rank_conf * 0.25 + src_conf * 0.25

        found.append({
            "value": value, "unit": unit, "confidence": base_confidence,
            "source_url": chunk.source_url, "snippet": chunk.text[:200],
        })

    if not found:
        return None

    groups = {}
    for f in found:
        key = (f["value"].strip().lower(), f["unit"].strip().lower())
        groups.setdefault(key, []).append(f)

    best_group = None
    best_group_score = -1
    for key, members in groups.items():
        distinct_sources = {m["source_url"] for m in members}
        top_member = max(members, key=lambda m: m["confidence"])
        agreement_bonus = 0.15 * (len(distinct_sources) - 1) if len(distinct_sources) > 1 else 0.0
        group_confidence = min(0.98, top_member["confidence"] + agreement_bonus)
        if group_confidence > best_group_score:
            best_group_score = group_confidence
            best_group = (top_member, len(distinct_sources), group_confidence)

    top_member, agreement_count, final_confidence = best_group
    return Extraction(
        label=label, value=top_member["value"], unit=top_member["unit"],
        confidence=round(final_confidence, 2), source_url=top_member["source_url"],
        snippet=top_member["snippet"], agreement_count=agreement_count,
    )


def extract_all_attributes(kb, attribute_queries: dict = None, min_confidence: float = 0.0,
                            errors: list = None):
    """
    Runs extract_attribute for every configured attribute. Returns list[Extraction].

    Fault isolation: each attribute's extraction is tried independently -
    one label's regex/normalization edge case (e.g. a malformed unit token
    slipping past normalize.normalize_uom) raising should not cost every
    OTHER attribute its already-successful extraction. Failures are
    swallowed and, if the caller passed an `errors` list, recorded there as
    (label, repr(exc)) so they're still visible in debug output rather than
    silently vanishing.
    """
    attribute_queries = attribute_queries or config.ATTRIBUTE_QUERIES
    results = []
    for label, spec in attribute_queries.items():
        try:
            ext = extract_attribute(kb, label, spec)
        except Exception as e:
            if errors is not None:
                errors.append((label, repr(e)))
            continue
        if ext and ext.confidence >= min_confidence:
            results.append(ext)
    return results


_DIM_LINE_RE = re.compile(
    r"(" + _NUM_FRAGMENT + r")\s*(in|mm|cm|ft)\s*([LWHD])\b", re.IGNORECASE
)


def parse_dimension_string(text: str) -> dict:
    """'24 in W x 24-1/4 in D' -> {'W': ('24','in'), 'D': ('24-1/4','in')}"""
    out = {}
    for m in _DIM_LINE_RE.finditer(text or ""):
        num, unit, axis = m.group(1), m.group(2), m.group(3).upper()
        out[axis] = (num, normalize.normalize_uom(unit))
    return out


def find_size_string(text: str):
    """
    Locates the composite 'NN in W x NN in D [x NN in H]' line that the
    guide's ground truth stores verbatim as ATTRIBUTE_VALUE for the
    'Size' label (e.g. '24 in W x 24-1/4 in D'). A line qualifies if it
    contains at least two axis-tagged dimension tokens (L/W/H/D) - a
    single dimension elsewhere (e.g. just a depth figure) is handled by
    the regular per-attribute extraction instead, not this composite one.
    Returns the trimmed matching line, or None.
    """
    for line in (text or "").splitlines():
        matches = list(_DIM_LINE_RE.finditer(line))
        if len(matches) >= 2:
            start, end = matches[0].start(), matches[-1].end()
            return line[start:end].strip()
    return None


_UPC_RE = re.compile(r"\b(\d{12})\b")
_GTIN_RE = re.compile(r"\b(\d{13,14})\b")


def find_code_near(text: str, keyword: str, pattern: re.Pattern, window: int = 60):
    low = text.lower()
    idx = low.find(keyword.lower())
    if idx == -1:
        return None
    span = text[max(0, idx - window): idx + len(keyword) + window]
    m = pattern.search(span)
    return m.group(1) if m else None


CERTIFICATION_PHRASES = [
    "UL Listed", "cUL Listed", "cULus Listed", "ETL Listed", "CSA Certified",
    "ENERGY STAR Certified", "ENERGY STAR Qualified", "NSF Certified", "NSF Listed",
    "RoHS Compliant", "FCC Compliant", "ADA Compliant", "Prop 65", "California Prop 65",
    "IECEE", "CEE Tier 2 Qualified", "CEE Tier 3 Qualified", "WaterSense Certified",
    "IP65 Rated", "IP66 Rated", "IP67 Rated", "ASSE 1006", "ASSE 1016", "ASSE 1070",
]
_CERT_RE = re.compile("|".join(re.escape(c) for c in
                                sorted(CERTIFICATION_PHRASES, key=len, reverse=True)), re.IGNORECASE)


def find_certifications(text: str) -> list:
    found, seen = [], set()
    for m in _CERT_RE.finditer(text or ""):
        canon = next(c for c in CERTIFICATION_PHRASES if c.lower() == m.group(0).lower())
        if canon.lower() not in seen:
            found.append(canon)
            seen.add(canon.lower())
    return found


_WITH_TRIGGER_RE = re.compile(r"\bWith\s+")
_TRADEMARK_TOKEN_RE = re.compile(r"\b([A-Z][A-Za-z]+(?:\u00ae|\u2122))\b")


def find_with_feature(text: str, max_words: int = 6):
    """
    Returns e.g. 'With CleanBoost' or 'With Washing 3rd Rack, Water
    Repellent Silverware Basket', or None. Captures verbatim from source
    text - never invents a feature name.

    Implementation note: greedily matching "With <a few words>" with a
    single regex over-captures whenever ordinary lowercase prose follows
    ("With CleanBoost technology for improved cleaning" would otherwise
    swallow "technology for improved cleaning" too). Manufacturer feature
    call-outs are Title Case ("CleanBoost", "Washing 3rd Rack"), so this
    walks word-by-word and stops at the first token that isn't part of a
    proper-noun-looking phrase (starts lowercase and isn't a short
    connector like "to"/"and").
    """
    m = _WITH_TRIGGER_RE.search(text or "")
    if not m:
        return _fallback_trademark_with(text)

    rest = text[m.end():]
    words = rest.split()
    connectors = {"to", "and", "&"}
    kept = []
    for w in words[:max_words]:
        bare = w.strip(",.;")
        starts_ok = bare[:1].isupper() or bare[:1].isdigit()
        if starts_ok or (w.lower().strip(",.;") in connectors and kept):
            kept.append(w)
            if not starts_ok:
                continue
        else:
            break
    phrase = " ".join(kept).rstrip(",.;")
    if phrase:
        return f"With {phrase}"
    return _fallback_trademark_with(text)


def _fallback_trademark_with(text: str):
    m2 = _TRADEMARK_TOKEN_RE.search(text or "")
    return f"With {m2.group(1)}" if m2 else None


FEATURE_SECTION_HINTS = (
    "feature", "highlight", "why you", "key benefit", "benefit",
    "specification", "overview", "selling-point", "selling_point",
)

_FEATURE_CLASS_RE = re.compile(
    r"feature|highlight|benefit|selling.?point|key.?spec|overview",
    re.IGNORECASE,
)


def _class_or_id_matches(tag) -> bool:
    """True when a tag's class or id attributes contain a feature-section hint."""
    for attr in ("class", "id"):
        val = tag.get(attr, "")
        if isinstance(val, list):
            val = " ".join(val)
        if val and _FEATURE_CLASS_RE.search(val):
            return True
    return False


def _li_texts_from(container, max_items: int, existing: list) -> list:
    """Extract unique, non-empty <li> texts from a container tag."""
    out = []
    seen = set(t.lower() for t in existing)
    for li in container.find_all("li"):
        txt = li.get_text(" ", strip=True)
        txt = re.sub(r"^[\s\u2022\-\*\d\.\)]+", "", txt).strip()
        if txt and txt.lower() not in seen and 8 < len(txt) < 200 and is_clean_text(txt):
            out.append(txt)
            seen.add(txt.lower())
        if len(out) >= max_items:
            break
    return out


def extract_feature_bullets(html_bytes: bytes, max_items: int = 20) -> list:
    """
    Returns a list of feature/highlight strings extracted verbatim from the
    page. Never invents content; returns [] when no recognizable feature
    section is found rather than making up bullets.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "lxml")
    bullets = []

    for heading in soup.find_all(re.compile(r"^h[1-4]$")):
        htext = heading.get_text(" ", strip=True).lower()
        if any(h in htext for h in FEATURE_SECTION_HINTS):
            sib = heading.find_next_sibling()
            while sib and sib.name not in ("h1", "h2", "h3", "h4"):
                lst = sib if sib.name in ("ul", "ol") else sib.find(["ul", "ol"])
                if lst:
                    bullets.extend(_li_texts_from(lst, max_items, bullets))
                    break
                sib = sib.find_next_sibling()
        if len(bullets) >= max_items:
            break

    if not bullets:
        for container in soup.find_all(["div", "section", "article", "aside"]):
            if not _class_or_id_matches(container):
                continue
            lst = container.find(["ul", "ol"])
            if lst:
                bullets.extend(_li_texts_from(lst, max_items, bullets))
            if len(bullets) >= max_items:
                break

    if not bullets:
        for container in soup.find_all(True):
            data_vals = " ".join(
                str(v) for k, v in container.attrs.items() if k.startswith("data-")
            )
            if _FEATURE_CLASS_RE.search(data_vals):
                lst = container.find(["ul", "ol"])
                if lst:
                    bullets.extend(_li_texts_from(lst, max_items, bullets))
                if len(bullets) >= max_items:
                    break

    if not bullets:
        for ul in soup.find_all(["ul", "ol"]):
            items = [li.get_text(" ", strip=True) for li in ul.find_all("li")]
            items = [i for i in items
                     if i and 8 < len(i) < 150
                     and not i.lower().startswith(("home", "about", "contact",
                                                    "sign in", "log in", "shop"))]
            if 2 <= len(items) <= 25:
                bullets = items[:max_items]
                break

    return bullets[:max_items]


def find_marketing_paragraph(text: str, min_words: int = 8, max_words: int = 70):
    """
    Picks the first clean prose paragraph from a page's marketing copy.
    """
    for para in re.split(r"\n\s*\n", text or ""):
        para = " ".join(para.split())
        if not para or not is_clean_text(para):
            continue
        wc = len(para.split())
        looks_like_label_line = bool(re.match(r"^[A-Za-z0-9 ]{2,40}[:\-]\s", para))
        if min_words <= wc <= max_words and not looks_like_label_line:
            return para
    return None


def find_page_images(html_bytes: bytes, base_url: str = "", max_images: int = 5):
    """
    og:image first (most reliable single "hero" product photo), then a
    handful of plain <img> tags as best-effort alternates. Relative paths
    are resolved against base_url. Purely structural HTML parsing - no
    image-classification model involved, so a page's decorative logo can
    slip in; that's an acceptable trade-off for a "best effort, don't
    fabricate" image field versus offering no alternates at all.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "lxml")
    urls = []

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        urls.append(urljoin(base_url, og["content"].strip()))

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        full = urljoin(base_url, src.strip())
        if full not in urls and any(full.lower().split("?")[0].endswith(ext)
                                     for ext in (".jpg", ".jpeg", ".png", ".webp")):
            urls.append(full)
        if len(urls) >= max_images:
            break
    return urls[:max_images]
