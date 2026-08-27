"""
pipeline.py
------------
Orchestrates the full per-row flow:

    clean -> (cache check) -> search -> fetch -> build KB
  -> extract attributes -> normalize -> classify -> build descriptions
  -> assemble a field dict with confidence + provenance per field

This is deliberately the ONLY module that calls multiple other modules
in sequence - everything else stays single-purpose and independently
testable (which is how every module above was actually tested, offline,
before being wired together here).

Two entry points:
  process_row(row, ...)                - full pipeline for one input row
  process_batch(df, ...)               - loops process_row sequentially
  process_batch_concurrent(df, ...)    - same, but rows run in a thread
                                          pool (I/O-bound work - search and
                                          page-fetch dominate wall time, so
                                          threads give a real speedup
                                          without fighting the GIL)

`live` toggles whether search_engine/fetch actually hit the network.
When False (offline/demo mode, or when injected_documents is supplied),
the pipeline runs entirely off pre-supplied or cached documents - this
is what makes the offline tests in this project deterministic, and it's
also a legitimate operating mode for a user who already has the manuals
downloaded locally.
"""
import re
import time
import concurrent.futures
from dataclasses import dataclass, field as dc_field

from . import (cleaning, normalize, search_engine, fetch, kb_index,
               extract, describe, classify, cache_store, config)

NOISE_DESC_TOKENS = re.compile(
    r"\b(display only|new in box|nib|open box|each|pack of \d+|\d+\s*pc|"
    r"\d+pc|clearance|discontinued)\b", re.IGNORECASE
)

FINISH_CODE_STOPLIST = {
    "ss", "bn", "wh", "bk", "or", "otr", "ea", "pc", "kit",
    "chrome", "nickel", "bronze", "brass", "black", "white", "gray", "grey",
    "stainless", "steel", "brushed", "satin", "polished", "oil-rubbed",
}

CATEGORY_ATTRIBUTE_TEMPLATES = {
    "dishwasher": [
        "Series", "Model", "Number of Wash Cycles", "Voltage Rating", "Amperage Rating",
        "Mounting Type", "Plug Type", "Size", "Depth With Door Open", "Minimum Height",
        "Maximum Height", "Sound Level", "Material", "Color", "Additional Information",
    ],
}


def lookup_attribute_template(fine_category: str):
    """
    Substring match, not exact equality: the classifier (or an eval-time
    LOV file) can hand back a specific leaf like "Built-In Dishwashers" or
    "Portable Dishwashers" - exact-matching against a fixed key would miss
    every variant. Whichever template key appears inside the category name
    wins; first match if more than one somehow does (unlikely given how
    few keys are seeded here).
    """
    low = (fine_category or "").lower()
    for key, template in CATEGORY_ATTRIBUTE_TEMPLATES.items():
        if key in low:
            return template
    return None


@dataclass
class FieldResult:
    value: str = ""
    confidence: float = 0.0
    source_url: str = ""
    snippet: str = ""


@dataclass
class RowResult:
    row_key: str
    fields: dict = dc_field(default_factory=dict)
    review_flags: list = dc_field(default_factory=list)
    debug: dict = dc_field(default_factory=dict)


REVIEW_THRESHOLD = 0.45


def _safe_call(result: RowResult, section: str, fn, *args, default=None, **kwargs):
    """
    Fault isolation at the sub-step level, not just the whole-row level.
    process_row runs many independent sections after the "core" fields
    (source/brand/classification/attributes) are already set - certifications,
    descriptions, feature bullets, images, document classification, etc. None
    of these should be able to take the row's ALREADY-successful fields down
    with them if one has an edge case (e.g. a page whose HTML trips up a
    regex). Runs fn(*args, **kwargs); on exception, records
    (section, repr(exc)) in result.debug["section_errors"] and returns
    `default` instead of propagating.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        result.debug.setdefault("section_errors", []).append((section, repr(e)))
        return default


def _set(result: RowResult, name: str, value, confidence=1.0, source_url="", snippet=""):
    result.fields[name] = FieldResult(value=str(value) if value is not None else "",
                                       confidence=confidence, source_url=source_url, snippet=snippet)
    if value and confidence < REVIEW_THRESHOLD:
        result.review_flags.append(name)


_TRUE_ES_PLURAL_RE = re.compile(r"(?:ss|sh|ch|x|zz)es$", re.IGNORECASE)


def _singularize(word: str) -> str:
    """
    'Dishwashers' -> 'Dishwasher', 'Belts' -> 'Belt', 'Boxes' -> 'Box',
    'Hoses' -> 'Hose'.

    English forms "-es" plurals two different ways, and naively chopping
    the last 2 characters off every "-es" word only gets ONE of them
    right: words ending in a genuine sibilant sound (ss/sh/ch/x/z, e.g.
    "Boxes", "Glasses", "Dishes") really do drop both letters to reach
    the singular. But words that already end in a silent "e" just add a
    plain "s" for their plural ("Hose" -> "Hoses", "Case" -> "Cases") -
    chopping 2 characters from those strips the "e" that belongs to the
    word itself ("Hoses" -> "Hos"). The regex below only chops 2 for the
    genuine-sibilant pattern; any other "-es" word only loses the "s".
    """
    low = word.lower()
    if _TRUE_ES_PLURAL_RE.search(low):
        return word[:-2]
    if low.endswith("es") and len(word) > 2:
        return word[:-1]
    if low.endswith("s") and not low.endswith("ss"):
        return word[:-1]
    return word


def guess_product_name(part_desc: str, part_num: str, fine_category: str = "") -> str:
    """
    Best-effort 'item type' noun (e.g. 'Dishwasher', 'Belt', 'Disc').
    Prefers fine category; otherwise strips part number, brand tokens,
    and finish codes from description, then looks for a recognizable
    item-type word (config.ITEM_TYPE_HINTS) before falling back to a
    purely positional guess.

    FIX (2026-08): this previously returned the FIRST leftover word no
    matter what it was, and - if NOTHING alpha survived filtering - fell
    back to a raw non-alpha token (a bare size string, e.g. '1/2"X18"')
    as if it were a product name. On abrasives-style rows ("5 IN FILM
    DISC 320 GRIT") that meant the material ("Film") or grit word won
    over the real item type ("Disc"), and on rows whose OWN description
    is just a differentiating size (a variant/child SKU with no item-type
    word at all in that particular cell) it printed the size itself as
    the "Product Name". Now: (1) a gazetteer match anywhere in the
    description wins over position, and (2) if no real word survives at
    all, this returns "" rather than inventing a value from a dimension
    string - matching this project's own "an empty-but-honest field beats
    an invented one" rule (see classify.py). pipeline.py already keeps a
    desc-only guess at low confidence, so a blank here still gets routed
    to human review same as before - it just won't show nonsense while
    it waits.
    """
    if fine_category:
        leaf = fine_category.split(">")[-1] if ">" in fine_category else fine_category
        leaf = _singularize(leaf.strip())
        words = leaf.split()
        if words and words[-1].lower() not in config.BLOCKED_BRAND_NAMES:
            return words[-1]

    desc = part_desc or ""
    if part_num:
        desc = re.sub(re.escape(part_num), "", desc, flags=re.IGNORECASE)
    desc = NOISE_DESC_TOKENS.sub("", desc)
    desc = re.sub(r"\s+-\s+.*$", "", desc)
    desc = desc.strip(" -")
    tokens = desc.split()
    if not tokens:
        return desc

    known_brand_tokens = set(normalize.SEED_BRANDS.keys()) | config.BLOCKED_BRAND_NAMES
    candidates = [
        t for t in tokens
        if not (len(t) <= 3 and t.isupper())
        and t.lower() not in FINISH_CODE_STOPLIST
        and t.lower() not in known_brand_tokens
    ]

    for t in candidates:
        bare = re.sub(r"[^A-Za-z]", "", t)
        if not bare:
            continue
        low = bare.lower()
        if low in config.ITEM_TYPE_HINTS or _singularize(bare).lower() in config.ITEM_TYPE_HINTS:
            return bare

    pool = [t for t in candidates if t.isalpha()]
    for cand in pool:
        if cand.lower() not in config.BLOCKED_BRAND_NAMES:
            return cand

    return ""


def gather_documents(mfr_url, ref_urls, doc_urls, live: bool, injected_documents=None,
                      errors: list = None):
    """
    Returns list[{"url":..., "text":...}] ready for kb_index. Runs OCR
    automatically when a PDF's text layer is too thin. `injected_documents`
    (list of the same shape) lets tests/offline mode/"I already have the
    manual" workflows skip search+fetch entirely.

    Fault isolation: each URL is processed independently, inside its own
    try/except. fetch.fetch_and_extract() already never raises for the
    download/parse steps (see fetch.py), but this loop also calls
    document parsing and touches dict keys from that result - wrapping
    the whole per-URL body means ANY unexpected failure on one document
    (a truly pathological PDF, a key that isn't there for some edge-case
    "kind") just skips that one document instead of losing every OTHER
    document already fetched for this same product. If `errors` is passed,
    (url, repr(exc)) pairs are appended there for debug visibility.
    """
    if injected_documents is not None:
        return injected_documents
    if not live:
        return []

    documents = []
    urls = [u for u in ([mfr_url] + list(ref_urls) + [d["url"] for d in doc_urls]) if u]
    for url in urls:
        try:
            result = fetch.fetch_and_extract(url)
            text = result.get("text", "")
            if result.get("kind") == "pdf" and result.get("needs_ocr"):
                continue
            if text:
                documents.append({
                    "url": url, "text": text, "meta": result.get("meta", {}),
                    "raw_html": result.get("raw") if result.get("kind") == "html" else None,
                })
        except Exception as e:
            if errors is not None:
                errors.append((url, repr(e)))
            continue
    return documents


def dynamic_enrich_attributes(part_num, part_desc, manufacturer_hint, effective_queries,
                               extractions, documents, kb, full_text, prose_text,
                               live: bool, injected_documents=None):
    """
    Dynamic enrichment (Approach 1): after the first search/extract pass,
    look at which configured attributes are STILL missing - never
    extracted, or extracted below config.ENRICHMENT_CONFIDENCE_THRESHOLD -
    and run ONE extra, narrowly-targeted search+fetch round aimed only at
    those labels (search_engine.find_enrichment_sources), instead of just
    accepting blanks/low-confidence values as final.

    Whatever new documents that turns up get folded into the SAME
    knowledge base and re-extracted for just the missing labels, so every
    downstream computation in process_row (Size string, dimensions,
    descriptions...) automatically benefits from the enriched
    kb/documents/full_text without process_row needing separate logic per
    field. Newly recovered values only ever ADD or IMPROVE - if the second
    pass finds a lower-confidence value than something already extracted,
    the original wins.

    Deliberately ONE extra round, not an iterative retry loop: look once at
    what's missing, ask once, stop. A row still missing attributes after
    this either genuinely isn't documented online, or needs a human - and
    it gets routed to review like any other low-confidence field rather
    than hammering search indefinitely.

    Skipped entirely off-network (mirrors the guard process_row already
    uses for the pass-1 search): never runs in offline mode or when the
    caller supplied injected_documents, so offline tests stay deterministic
    and a user's own locally-supplied manuals are never second-guessed with
    an unwanted live search.

    Never raises: any failure in the search/fetch/extract round is caught
    and recorded in the returned debug dict rather than losing the row's
    pass-1 results - this is fault isolation applied to enrichment itself.

    Returns (extractions, documents, kb, full_text, prose_text, debug_dict).
    """
    debug = {"enrichment_triggered": False}
    if not (config.ENABLE_DYNAMIC_ENRICHMENT and live and injected_documents is None):
        return extractions, documents, kb, full_text, prose_text, debug

    have = {e.label: e for e in extractions}
    missing_labels = [
        label for label in effective_queries
        if label not in have or have[label].confidence < config.ENRICHMENT_CONFIDENCE_THRESHOLD
    ]
    debug["enrichment_labels_missing"] = len(missing_labels)
    if len(missing_labels) < config.ENRICHMENT_MIN_MISSING:
        return extractions, documents, kb, full_text, prose_text, debug

    try:
        seen_urls = {d["url"] for d in documents}
        enrich = search_engine.find_enrichment_sources(
            part_num, part_desc, missing_labels, effective_queries,
            manufacturer_hint=manufacturer_hint, exclude_urls=seen_urls,
        )
        debug["enrichment_queries"] = enrich["queries"]
        new_urls = [u for u in enrich["urls"] if u not in seen_urls]
        if not new_urls:
            return extractions, documents, kb, full_text, prose_text, debug

        doc_errors = []
        new_docs = gather_documents(None, new_urls, [], live=live, errors=doc_errors)
        new_docs = [d for d in new_docs if d["url"] not in seen_urls]
        if doc_errors:
            debug["enrichment_document_errors"] = doc_errors[:config.MAX_DOCUMENT_ERRORS_KEPT]
        if not new_docs:
            return extractions, documents, kb, full_text, prose_text, debug

        documents = documents + new_docs
        kb = kb_index.build_part_kb(part_num, documents)
        full_text = "\n".join(d["text"] for d in documents)
        prose_text = "\n".join(d["text"] for d in documents if not d["url"].lower().endswith(".pdf"))

        missing_queries = {label: effective_queries[label] for label in missing_labels}
        recovery_errors = []
        recovered = (extract.extract_all_attributes(kb, missing_queries, errors=recovery_errors)
                     if kb.chunks else [])

        merged = {e.label: e for e in extractions}
        recovered_count = 0
        for e in recovered:
            prev = merged.get(e.label)
            if prev is None or e.confidence > prev.confidence:
                merged[e.label] = e
                recovered_count += 1
        extractions = list(merged.values())

        debug["enrichment_triggered"] = True
        debug["enrichment_new_documents"] = len(new_docs)
        debug["enrichment_labels_recovered"] = recovered_count
        if recovery_errors:
            debug["enrichment_extraction_errors"] = recovery_errors
    except Exception as e:
        debug["enrichment_error"] = repr(e)

    return extractions, documents, kb, full_text, prose_text, debug


def process_row(row: dict, live: bool = True, injected_documents=None) -> RowResult:
    row_start_time = time.time()
    row = cleaning.clean_row(row)
    part_num = row.get("Mfg_Part_Num", "")
    part_desc = row.get("Part_Desc", "")
    part_manuf = row.get("Part_Manuf", "")
    row_key = part_num or part_desc

    result = RowResult(row_key=row_key)

    for src_col, out_col in (("Mfg_Part_Num", "Mfg_Part_Num"), ("Part_Desc", "Part_Desc"),
                              ("E1_Brand", "E1_Brand"), ("Unilog_Brand", "Unilog_Brand"),
                              ("DIB_Brand", "DIB_Brand"), ("Part_Manuf", "Part_Manuf")):
        _set(result, out_col, row.get(src_col, ""), confidence=1.0)
    _set(result, "MANUFACTURER_PART_NUMBER", part_num, confidence=0.99)

    mb_seed = normalize.resolve_manufacturer_brand(part_manuf, part_desc, part_num=part_num)
    mfr_hint = mb_seed.get("brand_name") or mb_seed.get("manufacturer_name") or ""

    cached_source = cache_store.get_source(part_manuf or part_desc, part_num)
    source_from_cache = bool(cached_source and (cached_source["mfr_url"] or cached_source["ref_urls"]))
    if cached_source and (cached_source["mfr_url"] or cached_source["ref_urls"]):
        sources = {"mfr_url": cached_source["mfr_url"], "ref_urls": cached_source["ref_urls"],
                   "doc_urls": [{"kind": "cached", "url": u} for u in cached_source["doc_urls"]],
                   "site_name": "", "domain": ""}
        source_conf = 0.9
    elif live and injected_documents is None:
        sources = search_engine.find_sources(part_num, part_desc, manufacturer_hint=mfr_hint)
        source_conf = 0.55 if sources["mfr_url"] else 0.0
        if sources["mfr_url"]:
            cache_store.set_source(part_manuf or part_desc, part_num, sources["mfr_url"],
                                    sources["ref_urls"], [d["url"] for d in sources["doc_urls"]])
    else:
        sources = {"mfr_url": "", "ref_urls": [], "doc_urls": [], "site_name": "", "domain": ""}
        source_conf = 0.0

    _set(result, "MFR URL", sources["mfr_url"], confidence=source_conf, source_url=sources["mfr_url"])
    for i, url in enumerate(sources["ref_urls"][:config.MAX_REF_URLS], start=1):
        _set(result, f"Ref URL {i}", url, confidence=source_conf, source_url=url)

    document_errors = []
    documents = gather_documents(sources["mfr_url"], sources["ref_urls"], sources["doc_urls"],
                                  live=live, injected_documents=injected_documents,
                                  errors=document_errors)
    if document_errors:
        result.debug["document_errors"] = document_errors[:config.MAX_DOCUMENT_ERRORS_KEPT]
    kb = kb_index.build_part_kb(part_num, documents)
    full_text = "\n".join(d["text"] for d in documents)
    prose_text = "\n".join(d["text"] for d in documents if not d["url"].lower().endswith(".pdf"))

    page_site_name = next((d["meta"]["site_name"] for d in documents
                            if d.get("meta", {}).get("site_name")), "")
    if page_site_name.strip().lower() in config.BLOCKED_BRAND_NAMES:
        page_site_name = ""
    discovered_dom = sources.get("domain", "")
    if any(b in discovered_dom for b in config.BLOCKED_DOMAINS):
        discovered_dom = ""

    mb = normalize.resolve_manufacturer_brand(
        part_manuf, part_desc, part_num=part_num,
        discovered_domain=discovered_dom,
        discovered_site_name=page_site_name or sources.get("site_name", ""),
    )
    _set(result, "MANUFACTURER_NAME", mb["manufacturer_name"], confidence=mb["confidence"])
    _set(result, "BRAND_NAME", mb["brand_name"], confidence=mb["confidence"])
    if mb["source"] in ("web_discovery", "domain_guess") and part_num:
        cache_store.set_manufacturer_for_part(part_num, mb["manufacturer_name"], mb["brand_name"])

    cls = classify.classify(part_desc)
    if cls:
        _set(result, "Dept", cls["dept"], confidence=cls["confidence"])
        _set(result, "Class", cls["class"], confidence=cls["confidence"])
        _set(result, "Fine", cls["fine"], confidence=cls["confidence"])
        _set(result, "Classpath", cls["classpath"], confidence=cls["confidence"])
    fine_category = cls["fine"] if cls else ""

    product_name = guess_product_name(part_desc, part_num, fine_category)
    _set(result, "Product Name", product_name, confidence=0.6 if fine_category else 0.3)

    template = lookup_attribute_template(fine_category)

    if template:
        effective_queries = {}
        for label in template:
            effective_queries[label] = config.ATTRIBUTE_QUERIES.get(label) or {
                "synonyms": [label.lower()],
                "units": ["in", "ft", "mm", "cm", "V", "A", "dBA", "lb", "kg", "W", "Hz"],
            }
    else:
        effective_queries = dict(config.ATTRIBUTE_QUERIES)

    extraction_errors = []
    extractions = (extract.extract_all_attributes(kb, effective_queries, errors=extraction_errors)
                   if kb.chunks else [])
    if extraction_errors:
        result.debug["extraction_errors"] = extraction_errors

    extractions, documents, kb, full_text, prose_text, enrichment_debug = dynamic_enrich_attributes(
        part_num, part_desc, mb["manufacturer_name"], effective_queries, extractions,
        documents, kb, full_text, prose_text, live=live, injected_documents=injected_documents,
    )
    result.debug.update(enrichment_debug)

    size_str = extract.find_size_string(full_text) if full_text else None
    if size_str:
        extractions.append(extract.Extraction(label="Size", value=size_str, unit="",
                                                confidence=0.7, source_url=sources.get("mfr_url", ""),
                                                snippet=size_str))

    attr_map = {e.label: (e.value, e.unit) for e in extractions}
    conf_map = {e.label: e for e in extractions}

    if template:
        ordered_labels = template
    else:
        ordered_labels = [e.label for e in sorted(extractions, key=lambda x: -x.confidence)]

    for i, label in enumerate(ordered_labels[:config.MAX_ATTRIBUTES], start=1):
        e = conf_map.get(label)
        _set(result, f"ATTRIBUTE_LABEL {i}", label, confidence=0.8 if e else 0.4)
        if e:
            _set(result, f"ATTRIBUTE_VALUE {i}", e.value, confidence=e.confidence,
                 source_url=e.source_url, snippet=e.snippet)
            if e.unit:
                _set(result, f"ATTRIBUTE_UOM {i}", e.unit, confidence=e.confidence)

    dims = extract.parse_dimension_string(size_str) if size_str else {}
    dim_field_map = {"L": "LENGTH", "W": "WIDTH", "H": "HEIGHT"}
    for axis, out_name in dim_field_map.items():
        if axis in dims:
            val, unit = dims[axis]
            _set(result, out_name, val, confidence=0.7)
            _set(result, f"{out_name}_UOM", unit, confidence=0.7)
    if "Weight" in attr_map:
        val, unit = attr_map["Weight"]
        _set(result, "WEIGHT", val, confidence=conf_map["Weight"].confidence)
        _set(result, "WEIGHT_UOM", unit, confidence=conf_map["Weight"].confidence)

    certs = _safe_call(result, "certifications", extract.find_certifications, full_text, default=[]) or []
    if certs:
        _set(result, "Standard/Approvals", "|".join(certs), confidence=0.75)
    if any("prop 65" in c.lower() for c in certs):
        _set(result, "Prop 65", "Yes", confidence=0.7)

    with_feature_raw = _safe_call(result, "with_feature", extract.find_with_feature, prose_text)
    with_feature = with_feature_raw[5:] if with_feature_raw and with_feature_raw.startswith("With ") else ""
    if with_feature_raw:
        _set(result, "With", with_feature_raw, confidence=0.55, snippet=with_feature_raw)

    warranty = _safe_call(result, "warranty", extract.find_label_value, full_text, ["warranty"])
    if warranty:
        _set(result, "Warranty", warranty, confidence=0.6)

    upc = _safe_call(result, "upc", extract.find_code_near, full_text, "upc", extract._UPC_RE)
    if upc:
        _set(result, "UPC", upc, confidence=0.7)
    gtin = _safe_call(result, "gtin", extract.find_code_near, full_text, "gtin", extract._GTIN_RE)
    if gtin:
        _set(result, "GTIN", gtin, confidence=0.7)

    country = _safe_call(result, "country_of_origin", extract.find_label_value, full_text,
                          ["country of origin", "made in"])
    if country:
        _set(result, "Country Of Origin", country, confidence=0.55)

    if _safe_call(result, "discontinued_flag", lambda: bool(re.search(r"\bdiscontinued\b", full_text,
                                                                       re.IGNORECASE)), default=False):
        _set(result, "Discontinued", "Yes", confidence=0.6)

    series = attr_map.get("Series", ("", ""))[0]
    mpn = part_num
    brand_name = mb["brand_name"]
    manufacturer_name = mb["manufacturer_name"]

    def _build_descriptions():
        return (
            describe.build_invoice_desc(product_name, attr_map),
            describe.build_mobile_desc(manufacturer_name, brand_name, product_name, series, mpn),
            describe.build_short_desc(brand_name, series, mpn, product_name, with_feature, attr_map),
            describe.build_long_desc(brand_name, product_name, with_feature, series, attr_map),
            describe.build_retail_desc(series, product_name, attr_map),
        )
    desc_tuple = _safe_call(result, "descriptions", _build_descriptions, default=("", "", "", "", ""))
    invoice, mobile, short, long1, retail = desc_tuple

    desc_conf = 0.55 if extractions else 0.25
    _set(result, "INVOICE_DESC", invoice, confidence=desc_conf)
    _set(result, "MOBILE_DESC", mobile, confidence=desc_conf)
    _set(result, "SHORT_DESC", short, confidence=desc_conf)
    _set(result, "LONG_DESC1", long1, confidence=desc_conf)
    _set(result, "RETAIL_DESC", retail, confidence=desc_conf)

    feature_bullets = []
    for doc in documents:
        raw_html = doc.get("raw_html")
        if raw_html:
            feature_bullets = _safe_call(result, "feature_bullets", extract.extract_feature_bullets,
                                          raw_html, default=[]) or []
            if feature_bullets:
                break
    for i, bullet in enumerate(feature_bullets[:20], start=1):
        _set(result, f"ITEM_FEATURES_{i}", bullet, confidence=0.55)

    marketing_doc = next((d for d in documents if not d["url"].lower().endswith(".pdf")), None)
    marketing_para = (_safe_call(result, "marketing_paragraph", extract.find_marketing_paragraph, prose_text)
                       if prose_text else None)
    if marketing_para:
        _set(result, "MARKETING_DESCRIPTION", marketing_para, confidence=0.55,
             source_url=marketing_doc["url"] if marketing_doc else "", snippet=marketing_para)

    raw_brand = brand_name or manufacturer_name or ""
    if raw_brand.strip().lower() in config.BLOCKED_BRAND_NAMES:
        raw_brand = ""
    brand_token = re.sub(r"[^\w]+", "", raw_brand) or "Product"
    image_urls = []
    for doc in documents:
        if doc.get("raw_html"):
            found = _safe_call(result, "page_images", extract.find_page_images,
                                doc["raw_html"], base_url=doc["url"], default=[]) or []
            for url in found:
                if url not in image_urls:
                    image_urls.append(url)
        if len(image_urls) >= 5:
            break
    if image_urls and mpn:
        _set(result, "Product Image", f"{brand_token}_{mpn}.jpg", confidence=0.6, source_url=image_urls[0])
        _set(result, "Actual Image (Yes/No)", "Yes", confidence=0.6)
        for i, url in enumerate(image_urls[1:5], start=1):
            _set(result, f"Alternate Image {i}", f"{brand_token}_{mpn}_{i}.jpg", confidence=0.55, source_url=url)

    def _classify_pdf_kind(url: str) -> str:
        low = url.lower()
        if "install" in low:
            return "Instruction/Installation Manual"
        if any(k in low for k in ("owner", "user-guide", "usermanual")):
            return "Owners/User Manual"
        if "service" in low:
            return "Service Manual"
        if any(k in low for k in ("spec", "datasheet", "data-sheet", "specification")):
            return "Specification Sheet"
        return "Instruction/Installation Manual"

    doc_kind_suffix = {
        "Specification Sheet": "Specification_Sheet", "Instruction/Installation Manual": "Installation_Manual",
        "Owners/User Manual": "Owners_Manual", "Service Manual": "Service_Manual",
    }
    filled_doc_fields = set()
    if mpn:
        for doc in documents:
            if not doc["url"].lower().endswith(".pdf"):
                continue
            field_name = _classify_pdf_kind(doc["url"])
            if field_name in filled_doc_fields:
                continue
            filename = f"{brand_token}_{mpn}_{doc_kind_suffix[field_name]}.pdf"
            _set(result, field_name, filename, confidence=0.6, source_url=doc["url"])
            filled_doc_fields.add(field_name)

    result.debug["num_documents"] = len(documents)
    result.debug["num_chunks"] = len(kb.chunks)
    result.debug["sources"] = sources
    result.debug["source_from_cache"] = source_from_cache
    result.debug["mfr_url_found"] = bool(sources.get("mfr_url"))
    result.debug["ocr_used"] = any(d.get("used_ocr") for d in documents)
    result.debug["fields_populated"] = sum(1 for fr in result.fields.values() if fr.value)
    result.debug["fields_flagged"] = len(result.review_flags)
    result.debug["elapsed_seconds"] = round(time.time() - row_start_time, 3)
    return result


def process_batch(df, live: bool = True, progress_cb=None):
    """
    Loops process_row over a DataFrame, one at a time. progress_cb(i, total,
    row_key) is called after each row. Simple and predictable - good for
    small batches or debugging. For real batches in live mode, prefer
    process_batch_concurrent below: this sequential version pays the full
    search+fetch latency of every row back-to-back.

    FIX (2026-08 robustness pass): this previously called process_row()
    directly, unguarded - a single row raising (a truly unexpected failure
    that made it past every other layer of fault isolation in this file)
    would crash the whole loop and lose every row already processed before
    it, plus every row after it. process_batch_concurrent already routed
    through _safe_process_row for exactly this reason; this sequential
    entry point now does the same, so "one bad product doesn't stop the
    batch" holds regardless of which entry point a caller uses.
    """
    results = []
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        _, r, _ = _safe_process_row(i, row.to_dict(), live)
        results.append(r)
        if progress_cb:
            progress_cb(i, total, r.row_key)
    return results


def _safe_process_row(index, row_dict, live):
    """
    Wraps process_row so one row's unexpected failure (a broken PDF, a
    site that times out, an OCR error that somehow escapes ocr.py's own
    handling) can never take down the rest of a concurrent batch. Returns
    (index, RowResult, elapsed_seconds) - the index is what lets the
    caller put results back in the original input order even though
    threads finish in whatever order they finish in.
    """
    t0 = time.time()
    try:
        r = process_row(row_dict, live=live)
    except Exception as e:
        r = RowResult(row_key=row_dict.get("Mfg_Part_Num", f"row_{index}"))
        for src_col in ("Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand",
                         "DIB_Brand", "Part_Manuf"):
            r.fields[src_col] = FieldResult(value=str(row_dict.get(src_col, "")))
        r.debug["error"] = repr(e)
        r.debug["elapsed_seconds"] = round(time.time() - t0, 3)
    return index, r, time.time() - t0


def process_batch_concurrent(df, live: bool = True, max_workers: int = 4, per_row_cb=None):
    """
    Same job as process_batch, but rows run concurrently in a thread pool.
    This is an I/O-bound workload - a row's wall-clock time is almost
    entirely spent waiting on network round-trips (DuckDuckGo, manufacturer
    sites), not CPU, so threads give a near-linear speedup up to a point
    without fighting Python's GIL the way CPU-bound work would. Every
    module that gets touched concurrently was made safe for this
    deliberately: cache_store opens a fresh SQLite connection per call
    (WAL mode + a lock-wait timeout, not a shared connection) and
    search_engine gives each thread its own DDGS client instead of
    sharing one.

    max_workers is a real trade-off, not just a knob: too high and
    DuckDuckGo/manufacturer sites are more likely to rate-limit or block
    you, which slows things down worse than running sequentially would
    have. 4-6 is a reasonable default; raise it cautiously.

    per_row_cb(index, RowResult, elapsed_seconds) fires as soon as EACH
    row finishes (not in input order) - this is what lets the frontend
    update a row's entry the moment it's done instead of waiting for
    the whole batch, per your request.

    Returns list[RowResult] in the SAME ORDER as the input DataFrame,
    regardless of the order threads actually finished in.
    """
    rows = [(i, row.to_dict()) for i, (_, row) in enumerate(df.iterrows())]
    results = [None] * len(rows)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_safe_process_row, i, row_dict, live) for i, row_dict in rows]
        for future in concurrent.futures.as_completed(futures):
            index, r, elapsed = future.result()
            results[index] = r
            if per_row_cb:
                per_row_cb(index, r, elapsed)

    return results


def summarize_batch(results: list, wall_clock_seconds: float = None) -> dict:
    """
    Aggregate stats across a completed batch - what "more statistics" means
    in practice: not just field counts, but where the time actually went
    and how much the self-learning cache is paying off.
    """
    n = len(results)
    times = [r.debug.get("elapsed_seconds") for r in results if r.debug.get("elapsed_seconds") is not None]
    cache_hits = sum(1 for r in results if r.debug.get("source_from_cache"))
    ocr_used = sum(1 for r in results if r.debug.get("ocr_used"))
    mfr_found = sum(1 for r in results if r.debug.get("mfr_url_found"))
    errors = sum(1 for r in results if r.debug.get("error"))
    fields_populated = [r.debug.get("fields_populated", 0) for r in results]
    fields_flagged = [r.debug.get("fields_flagged", 0) for r in results]

    enrichment_triggered = sum(1 for r in results if r.debug.get("enrichment_triggered"))
    enrichment_recovered = sum(r.debug.get("enrichment_labels_recovered", 0) for r in results)

    rows_with_document_errors = sum(1 for r in results if r.debug.get("document_errors"))
    rows_with_section_errors = sum(1 for r in results if r.debug.get("section_errors"))

    return {
        "rows": n,
        "wall_clock_seconds": wall_clock_seconds,
        "avg_row_seconds": (sum(times) / len(times)) if times else 0.0,
        "min_row_seconds": min(times) if times else 0.0,
        "max_row_seconds": max(times) if times else 0.0,
        "throughput_rows_per_min": (n / wall_clock_seconds * 60) if wall_clock_seconds else None,
        "cache_hit_rate": (cache_hits / n) if n else 0.0,
        "ocr_used_count": ocr_used,
        "mfr_url_found_rate": (mfr_found / n) if n else 0.0,
        "error_count": errors,
        "avg_fields_populated": (sum(fields_populated) / n) if n else 0.0,
        "avg_fields_flagged": (sum(fields_flagged) / n) if n else 0.0,
        "enrichment_triggered_count": enrichment_triggered,
        "enrichment_triggered_rate": (enrichment_triggered / n) if n else 0.0,
        "enrichment_labels_recovered": enrichment_recovered,
        "rows_with_document_errors": rows_with_document_errors,
        "rows_with_section_errors": rows_with_section_errors,
    }