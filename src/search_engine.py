"""
search_engine.py
------------------
Free web search via DuckDuckGo (the `ddgs` package - no API key, no
quota). This encodes the guide's sourcing hierarchy directly into how
queries are built and ranked: manufacturer's own domain and official
documentation first, marketplaces/pure distributor sites excluded.

Strategy per part:
  1. If the part's manufacturer family is already in source_cache (a human
     verified it earlier in this batch, or a previous run), skip search
     entirely and reuse the verified URLs. This is the main efficiency
     lever of the human-in-the-loop design.
  2. Otherwise run 2-3 targeted queries (identity search, PDF/manual
     search, spec search), merge + dedupe + rank results by domain trust.

FIX (2026-08): Added the missing return block (the function was building
`ranked` but never returning it, so every call got None → empty sources
→ source_conf=0 for all rows). Also improved trust_score() to properly
differentiate manufacturer homepages, spec PDFs, and other pages.
"""
import re
import threading
import time
from collections import Counter
from urllib.parse import urlparse

from . import config


_thread_local = threading.local()

_ddgs_client = None


def _get_client():
    client = getattr(_thread_local, "ddgs_client", None)
    if client is None:
        from ddgs import DDGS
        client = DDGS()
        _thread_local.ddgs_client = client
    return client


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _is_homepage(url: str) -> bool:
    """
    Returns True when the URL looks like a manufacturer's root homepage
    rather than a deep product/support page. A path of '' '/' or at most
    one non-empty segment (e.g. '/products') qualifies.
    Used to prefer 'frigidaire.com' over 'frigidaire.com/support/manuals/...'
    as the MFR URL, matching the guide's intent for that field.
    """
    try:
        path = urlparse(url).path.strip("/")
        segments = [s for s in path.split("/") if s]
        return len(segments) <= 1
    except Exception:
        return False


def is_blocked(url: str) -> bool:
    if not url:
        return True
    d = _domain(url)
    if not d:
        return True
    for b in config.BLOCKED_DOMAINS:
        if d == b or d.endswith("." + b) or b in d:
            return True
    low_url = url.lower()
    if any(k in low_url for k in ("/compare/", ".patch", ".diff", "/pull/", "/commit/", "/blob/", "/raw/", "/tree/")):
        return True
    return False


def trust_score(url: str) -> float:
    """
    Higher is better. Manufacturer-looking own-domain hits and files that
    look like manuals/spec sheets score highest; blocked marketplaces are
    filtered out entirely before this is even called.
    """
    if is_blocked(url):
        return -1.0
    score = 0.40
    low = url.lower()
    if low.endswith(".pdf"):
        score += 0.40
    if any(h in low for h in config.TRUSTED_DOC_HINTS):
        score += 0.20
    if _is_homepage(url):
        score += 0.15
    return min(score, 1.0)


def raw_search(query: str, max_results: int = 8, retries: int = 2):
    """Thin retry wrapper around ddgs.text() - network errors happen."""
    client = _get_client()
    last_err = None
    for attempt in range(retries + 1):
        try:
            return list(client.text(query, max_results=max_results))
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"search failed for {query!r}: {last_err}")


def build_queries(part_num: str, part_desc: str, manufacturer_hint: str = ""):
    """
    Returns an ordered list of (query, purpose) tuples. Order matters:
    identity first (who makes this + where's their site), then documents.
    """
    part_num = (part_num or "").strip()
    clean_desc = re.sub(re.escape(part_num), "", part_desc or "", flags=re.IGNORECASE).strip()
    desc_terms = " ".join(clean_desc.split()[:5])
    queries = []

    hint = manufacturer_hint or ""
    if not hint and part_desc:
        first_tok = (part_desc.split()[0] if part_desc.split() else "").strip()
        if len(first_tok) >= 2 and first_tok.isalnum() and first_tok.lower() not in config.BLOCKED_BRAND_NAMES:
            hint = first_tok

    if hint:
        queries.append((f'{hint} "{part_num}" official datasheet specification', "identity"))
        queries.append((f'{hint} "{part_num}" manual filetype:pdf', "manual_pdf"))
        queries.append((f'{hint} "{part_num}" specification sheet filetype:pdf', "spec_pdf"))
    else:
        queries.append((f'"{part_num}" {desc_terms} datasheet specification', "identity"))
        queries.append((f'"{part_num}" manual filetype:pdf', "manual_pdf"))
        queries.append((f'"{part_num}" specification sheet filetype:pdf', "spec_pdf"))

    return queries


def find_sources(part_num: str, part_desc: str, manufacturer_hint: str = "",
                  max_urls: int = config.MAX_REF_URLS):
    """
    Runs the query plan, filters blocked domains, ranks by trust, returns:
      {
        "mfr_url": best single non-PDF page (identity candidate) or "",
        "ref_urls": [...],           # up to max_urls best supporting pages
        "doc_urls": [{...}, ...],    # PDFs found, classified by keyword
        "site_name": "",             # domain-derived brand guess for normalize.py
        "domain": "",
        "raw_hits": [...]            # everything found, for debugging/audit
      }

    Official-site prioritization: a domain that shows up across MULTIPLE
    independent queries (the identity search AND the manual search AND
    the spec search all pointing at the same domain) is far more likely
    to be the manufacturer's real site than one that only appears once -
    that's a genuine consensus signal search ranking alone doesn't give
    us, and it costs nothing extra since these are the same search calls
    we're already making. Each additional query that agrees adds a
    bounded trust bonus (capped so it can never let a marketplace-tier
    hit outrank a single clean manufacturer-domain match).

    FIX (2026-08): Added the missing return block. The function was
    previously computing `ranked` but never returning anything, so every
    call fell through to the empty-sources fallback in pipeline.py.
    Also added homepage-preference logic for the mfr_url field.
    """
    all_hits = []
    for query, purpose in build_queries(part_num, part_desc, manufacturer_hint):
        try:
            hits = raw_search(query, max_results=6)
        except RuntimeError:
            continue
        for h in hits:
            url = h.get("href") or h.get("url") or ""
            if not url or is_blocked(url):
                continue
            all_hits.append({"url": url, "title": h.get("title", ""), "purpose": purpose,
                              "score": trust_score(url)})

    domain_query_hits = {}
    for h in all_hits:
        d = _domain(h["url"])
        domain_query_hits.setdefault(d, set()).add(h["purpose"])
    for h in all_hits:
        consensus = len(domain_query_hits.get(_domain(h["url"]), set()))
        h["score"] = min(1.0, h["score"] + 0.12 * max(0, consensus - 1))

    best = {}
    for h in all_hits:
        if h["url"] not in best or h["score"] > best[h["url"]]["score"]:
            best[h["url"]] = h
    ranked = sorted(best.values(), key=lambda h: h["score"], reverse=True)

    doc_urls = []
    html_hits = []

    for h in ranked:
        url = h["url"]
        if url.lower().endswith(".pdf"):
            doc_urls.append({"kind": _classify_pdf_purpose(url), "url": url, "score": h["score"]})
        else:
            html_hits.append(h)

    mfr_url = ""
    site_name = ""
    domain = ""
    if html_hits:
        top_domain = _domain(html_hits[0]["url"])
        domain = top_domain
        same_domain_hits = [h for h in html_hits if _domain(h["url"]) == top_domain]
        same_domain_hits.sort(key=lambda h: (not _is_homepage(h["url"]), -h["score"]))
        mfr_url = same_domain_hits[0]["url"]
        core = top_domain.split(".")[0]
        site_name = re.sub(r"[-_]", " ", core).title()
        if site_name.strip().lower() in config.BLOCKED_BRAND_NAMES or any(b in top_domain for b in config.BLOCKED_DOMAINS):
            site_name = ""
            domain = ""
            mfr_url = ""

    ref_urls = [h["url"] for h in html_hits if h["url"] != mfr_url and not is_blocked(h["url"])][:max_urls]

    return {
        "mfr_url": mfr_url,
        "ref_urls": ref_urls,
        "doc_urls": doc_urls,
        "site_name": site_name,
        "domain": domain,
        "raw_hits": ranked,
    }


def build_attribute_queries(part_num: str, missing_labels: list, attribute_queries: dict,
                             manufacturer_hint: str = "", max_labels: int = 5):
    """
    Dynamic enrichment's query plan: instead of re-running the same generic
    identity/manual/spec queries from build_queries() again, ask specifically
    for the attributes that are still missing after the first pass. Each
    missing label gets its own short query built from that label's own
    synonyms (config.ATTRIBUTE_QUERIES), so a search for "Sound Level" isn't
    diluted by also asking about "Voltage Rating" in the same query string.

    Bounded to max_labels queries - a row missing 15 attributes still only
    costs at most max_labels extra network round-trips, not 15.
    """
    part_num = (part_num or "").strip()
    queries = []
    for label in missing_labels[:max_labels]:
        spec = attribute_queries.get(label) or {}
        synonyms = spec.get("synonyms") or [label.lower()]
        syn_clause = " OR ".join(f'"{s}"' for s in synonyms[:2])
        if manufacturer_hint:
            queries.append((f'{manufacturer_hint} "{part_num}" {label}', f"attr:{label}"))
        else:
            queries.append((f'"{part_num}" {syn_clause}', f"attr:{label}"))
    return queries


def find_enrichment_sources(part_num: str, part_desc: str, missing_labels: list,
                             attribute_queries: dict, manufacturer_hint: str = "",
                             exclude_urls=None, max_urls: int = None, max_labels: int = None):
    """
    Second-round search for dynamic enrichment. Same ranking/trust/blocked-
    domain machinery as find_sources(), but the query plan targets exactly
    the attributes still missing rather than generic identity queries -
    that's the whole point of this being a separate function instead of
    just calling find_sources() again (which would re-fetch the exact same
    pages and find nothing new).

    exclude_urls lets the caller skip anything already fetched in pass 1,
    so enrichment only spends network calls on genuinely new pages.

    Returns {"urls": [...], "raw_hits": [...], "queries": [...]}.
    """
    max_urls = max_urls if max_urls is not None else config.ENRICHMENT_MAX_NEW_URLS
    max_labels = max_labels if max_labels is not None else config.ENRICHMENT_MAX_LABELS
    exclude_urls = exclude_urls or set()

    query_plan = build_attribute_queries(part_num, missing_labels, attribute_queries,
                                          manufacturer_hint, max_labels)
    all_hits = []
    for query, purpose in query_plan:
        try:
            hits = raw_search(query, max_results=5)
        except RuntimeError:
            continue
        for h in hits:
            url = h.get("href") or h.get("url") or ""
            if not url or is_blocked(url) or url in exclude_urls:
                continue
            all_hits.append({"url": url, "title": h.get("title", ""), "purpose": purpose,
                              "score": trust_score(url)})

    best = {}
    for h in all_hits:
        if h["url"] not in best or h["score"] > best[h["url"]]["score"]:
            best[h["url"]] = h
    ranked = sorted(best.values(), key=lambda h: h["score"], reverse=True)

    return {
        "urls": [h["url"] for h in ranked[:max_urls]],
        "raw_hits": ranked,
        "queries": [q for q, _ in query_plan],
    }


def _classify_pdf_purpose(url: str) -> str:
    """Classify a PDF URL by keyword for doc_urls 'kind' field."""
    low = url.lower()
    if any(k in low for k in ("spec", "datasheet", "data-sheet", "specification")):
        return "spec"
    if any(k in low for k in ("install", "installation")):
        return "install"
    if any(k in low for k in ("owner", "user-guide", "usermanual")):
        return "owner"
    if "service" in low:
        return "service"
    return "manual"
