"""
fetch.py
---------
Downloads a URL (HTML page or PDF) and turns it into clean text, with a
local disk cache keyed by URL hash so nothing gets fetched twice across
a batch run (important since some manufacturers rate-limit).

HTML -> trafilatura (rule-based main-content extraction: strips nav,
        ads, footers - no ML) with a BeautifulSoup fallback.
PDF  -> PyMuPDF text layer. If the text layer is too thin (scanned
        document), ocr.py takes over.
"""
import os
import hashlib
import requests
import trafilatura
from bs4 import BeautifulSoup

from . import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 TraceForgeBot/1.0"
}
TIMEOUT = 20


def _cache_path(url: str, suffix: str) -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return os.path.join(config.DOC_CACHE_DIR, f"{h}{suffix}")


def _download(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.content


def fetch_raw(url: str, force: bool = False) -> bytes:
    """Download and disk-cache the raw bytes of a URL."""
    suffix = ".pdf" if url.lower().endswith(".pdf") else ".html"
    cpath = _cache_path(url, suffix)
    if not force and os.path.exists(cpath):
        with open(cpath, "rb") as f:
            return f.read()
    content = _download(url)
    with open(cpath, "wb") as f:
        f.write(content)
    return content


def clear_document_cache() -> int:
    """Remove cached raw web documents while preserving the learned cache."""
    removed = 0
    for name in os.listdir(config.DOC_CACHE_DIR):
        if not name.lower().endswith((".html", ".pdf")):
            continue
        path = os.path.join(config.DOC_CACHE_DIR, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                continue
    return removed


def extract_html_text(html_bytes: bytes) -> str:
    html = html_bytes.decode("utf-8", errors="ignore")
    text = trafilatura.extract(html, include_tables=True, favor_recall=True)
    if not text:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    return text or ""


def extract_page_meta(html_bytes: bytes) -> dict:
    """Pull og:site_name / og:image / title - cheap, rule-based identity signals."""
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "lxml")
    meta = {}
    site_name = soup.find("meta", property="og:site_name")
    meta["site_name"] = site_name["content"].strip() if site_name and site_name.get("content") else ""
    image = soup.find("meta", property="og:image")
    meta["image"] = image["content"].strip() if image and image.get("content") else ""
    meta["title"] = soup.title.get_text(strip=True) if soup.title else ""
    return meta


def extract_pdf_text(pdf_bytes: bytes, min_chars_per_page: int = 40):
    """
    Returns (text, needs_ocr: bool). Uses PyMuPDF's text layer; if the
    average characters-per-page is very low, the PDF is probably scanned
    and the caller should fall back to ocr.py.
    """
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text("text"))
    doc.close()
    text = "\n".join(pages_text)
    avg_density = (len(text) / max(len(pages_text), 1))
    return text, avg_density < min_chars_per_page


def fetch_and_extract(url: str):
    """
    One-stop entry point used by kb_index.py. Returns:
      {"url":..., "text":..., "meta": {...}, "kind": "html"|"pdf", "needs_ocr": bool}
    Never raises - on any failure returns text="" so the pipeline can carry on.

    FIX (2026-08 robustness pass): the download step (fetch_raw) was already
    guarded, but the PARSING steps below it (extract_pdf_text / extract_html_text
    / extract_page_meta) were not - a single malformed PDF (bad xref table, an
    HTML page mislabeled as a PDF, etc.) raised straight out of this function,
    contradicting its own "never raises" docstring. That exception would only
    ever get caught back at the whole-ROW level (pipeline._safe_process_row),
    which meant one bad document could discard everything else already found
    for that product. Wrapping the parse step here means a single bad
    document is isolated at the DOCUMENT level instead - the pipeline just
    skips it and keeps the other, good documents for that same part.
    """
    try:
        raw = fetch_raw(url)
    except Exception as e:
        return {"url": url, "text": "", "meta": {}, "kind": "error", "needs_ocr": False, "error": str(e)}

    try:
        if url.lower().endswith(".pdf"):
            text, needs_ocr = extract_pdf_text(raw)
            return {"url": url, "text": text, "meta": {}, "kind": "pdf", "needs_ocr": needs_ocr, "raw": raw}
        else:
            text = extract_html_text(raw)
            meta = extract_page_meta(raw)
            return {"url": url, "text": text, "meta": meta, "kind": "html", "needs_ocr": False, "raw": raw}
    except Exception as e:
        return {"url": url, "text": "", "meta": {}, "kind": "error", "needs_ocr": False, "error": str(e)}
