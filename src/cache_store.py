"""
cache_store.py
---------------
The memory behind the human-in-the-loop innovation.

Every value a human approves or corrects in the Streamlit review UI is
written here, keyed so that it is reusable by *other* rows, not just the
one being edited. Three lookup tables + one audit log:

  manufacturer_alias   messy string  -> canonical (manufacturer, brand)
  classpath_cache       description signature -> (Dept, Class, Fine, Classpath)
  source_cache          manufacturer + part-pattern -> verified MFR URL / doc URLs
  correction_log         full audit trail (row id, field, old, new, source, ts)

Because the key for source_cache and classpath_cache is a *pattern*
(manufacturer + product-line prefix / description signature) rather than
the exact part number, one human correction on row 12 can silently
pre-fill row 340 if it belongs to the same product family - this is the
"propagation" behavior the UI uses to cut down repeat review work as a
batch progresses. It is deliberately simple (SQLite, exact/fuzzy keys,
no model) so it is auditable and needs no LLM.
"""
import sqlite3
import time
import re
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS manufacturer_alias (
    raw_key TEXT PRIMARY KEY,          -- normalized lowercase input string
    manufacturer_name TEXT,
    brand_name TEXT,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS part_manufacturer (
    part_family_key TEXT PRIMARY KEY,  -- product_line_prefix(part_num), normalized
    manufacturer_name TEXT,
    brand_name TEXT,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS classpath_cache (
    signature TEXT PRIMARY KEY,        -- normalized keyword signature of description
    dept TEXT,
    class TEXT,
    fine TEXT,
    classpath TEXT,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS source_cache (
    pattern_key TEXT PRIMARY KEY,      -- manufacturer + product-line prefix
    mfr_url TEXT,
    ref_urls TEXT,                     -- pipe-separated
    doc_urls TEXT,                     -- json-ish pipe-separated "kind::url"
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS correction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_key TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    source_url TEXT,
    action TEXT,                       -- 'approved' | 'edited' | 'rejected'
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS field_confidence (
    row_key TEXT,
    field TEXT,
    confidence REAL,
    source_url TEXT,
    snippet TEXT,
    PRIMARY KEY (row_key, field)
);
"""


@contextmanager
def _conn():
    c = sqlite3.connect(config.DB_PATH, timeout=15)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def product_line_prefix(part_num: str) -> str:
    """
    Strip trailing variant characters (color/size suffixes) from a part
    number to get a family key, e.g. WDTS7024RZ -> WDTS7024. This is a
    conservative heuristic (drop trailing alpha run of length <=2 that
    follows digits) so sibling SKUs of the same product family share a
    cache key without merging unrelated numbers.
    """
    m = re.match(r"^(.*\d)([A-Za-z]{1,2})$", (part_num or "").strip())
    return m.group(1) if m else (part_num or "").strip()



def get_manufacturer_alias(raw_string: str):
    key = _norm(raw_string)
    if not key:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT manufacturer_name, brand_name FROM manufacturer_alias WHERE raw_key=?",
            (key,),
        ).fetchone()
    if not row:
        return None
    res = dict(row)
    if (res.get("manufacturer_name") or "").strip().lower() in config.BLOCKED_BRAND_NAMES:
        return None
    return res


def set_manufacturer_alias(raw_string: str, manufacturer_name: str, brand_name: str = ""):
    key = _norm(raw_string)
    if not key or manufacturer_name.strip().lower() in config.BLOCKED_BRAND_NAMES:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO manufacturer_alias (raw_key, manufacturer_name, brand_name, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(raw_key) DO UPDATE SET "
            "manufacturer_name=excluded.manufacturer_name, brand_name=excluded.brand_name, "
            "updated_at=excluded.updated_at",
            (key, manufacturer_name, brand_name, time.time()),
        )


def get_manufacturer_for_part(part_num: str):
    key = _norm(product_line_prefix(part_num))
    if not key:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT manufacturer_name, brand_name FROM part_manufacturer WHERE part_family_key=?",
            (key,),
        ).fetchone()
    if not row:
        return None
    res = dict(row)
    if (res.get("manufacturer_name") or "").strip().lower() in config.BLOCKED_BRAND_NAMES:
        return None
    return res


def set_manufacturer_for_part(part_num: str, manufacturer_name: str, brand_name: str = ""):
    key = _norm(product_line_prefix(part_num))
    if not key or manufacturer_name.strip().lower() in config.BLOCKED_BRAND_NAMES:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO part_manufacturer (part_family_key, manufacturer_name, brand_name, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(part_family_key) DO UPDATE SET "
            "manufacturer_name=excluded.manufacturer_name, brand_name=excluded.brand_name, "
            "updated_at=excluded.updated_at",
            (key, manufacturer_name, brand_name, time.time()),
        )



def description_signature(desc: str) -> str:
    """Cheap, deterministic signature: sorted significant tokens (len>=4)."""
    tokens = re.findall(r"[a-z]{4,}", (desc or "").lower())
    stop = {"with", "display", "only", "each", "pack"}
    tokens = sorted(set(t for t in tokens if t not in stop))
    return " ".join(tokens[:8])


def get_classpath(desc: str):
    sig = description_signature(desc)
    if not sig:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT dept, class, fine, classpath FROM classpath_cache WHERE signature=?",
            (sig,),
        ).fetchone()
    return dict(row) if row else None


def set_classpath(desc: str, dept: str, cls: str, fine: str, classpath: str):
    sig = description_signature(desc)
    if not sig:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO classpath_cache (signature, dept, class, fine, classpath, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(signature) DO UPDATE SET "
            "dept=excluded.dept, class=excluded.class, fine=excluded.fine, "
            "classpath=excluded.classpath, updated_at=excluded.updated_at",
            (sig, dept, cls, fine, classpath, time.time()),
        )



def source_key(manufacturer: str, part_num: str) -> str:
    return f"{_norm(manufacturer)}::{_norm(product_line_prefix(part_num))}"


def get_source(manufacturer: str, part_num: str):
    key = source_key(manufacturer, part_num)
    with _conn() as c:
        row = c.execute(
            "SELECT mfr_url, ref_urls, doc_urls FROM source_cache WHERE pattern_key=?",
            (key,),
        ).fetchone()
    if not row:
        return None
    from . import search_engine
    mfr_url = row["mfr_url"] or ""
    if mfr_url and search_engine.is_blocked(mfr_url):
        return None
    ref_urls = [u for u in (row["ref_urls"] or "").split("|") if u and not search_engine.is_blocked(u)]
    doc_urls = [u for u in (row["doc_urls"] or "").split("|") if u and not search_engine.is_blocked(u)]
    return {
        "mfr_url": mfr_url,
        "ref_urls": ref_urls,
        "doc_urls": doc_urls,
    }


def set_source(manufacturer: str, part_num: str, mfr_url: str, ref_urls=None, doc_urls=None):
    from . import search_engine
    if mfr_url and search_engine.is_blocked(mfr_url):
        mfr_url = ""
    clean_ref = [u for u in (ref_urls or []) if u and not search_engine.is_blocked(u)]
    clean_doc = [u for u in (doc_urls or []) if u and not search_engine.is_blocked(u)]
    key = source_key(manufacturer, part_num)
    with _conn() as c:
        c.execute(
            "INSERT INTO source_cache (pattern_key, mfr_url, ref_urls, doc_urls, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(pattern_key) DO UPDATE SET "
            "mfr_url=excluded.mfr_url, ref_urls=excluded.ref_urls, doc_urls=excluded.doc_urls, "
            "updated_at=excluded.updated_at",
            (key, mfr_url or "", "|".join(clean_ref), "|".join(clean_doc), time.time()),
        )



def log_correction(row_key, field, old_value, new_value, source_url, action):
    with _conn() as c:
        c.execute(
            "INSERT INTO correction_log (row_key, field, old_value, new_value, source_url, action, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (row_key, field, old_value, new_value, source_url, action, time.time()),
        )


def set_confidence(row_key, field, confidence, source_url="", snippet=""):
    with _conn() as c:
        c.execute(
            "INSERT INTO field_confidence (row_key, field, confidence, source_url, snippet) "
            "VALUES (?,?,?,?,?) ON CONFLICT(row_key, field) DO UPDATE SET "
            "confidence=excluded.confidence, source_url=excluded.source_url, snippet=excluded.snippet",
            (row_key, field, confidence, source_url, snippet),
        )


def get_confidence(row_key, field):
    with _conn() as c:
        row = c.execute(
            "SELECT confidence, source_url, snippet FROM field_confidence WHERE row_key=? AND field=?",
            (row_key, field),
        ).fetchone()
    return dict(row) if row else None


def stats():
    with _conn() as c:
        out = {}
        for t in ("manufacturer_alias", "classpath_cache", "source_cache", "correction_log"):
            out[t] = c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    return out
