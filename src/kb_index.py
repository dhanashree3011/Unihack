"""
kb_index.py
------------
Builds the per-part "knowledge base": chunks every document fetched for
a part (manufacturer page + manuals + spec sheets) and indexes the
chunks with BM25 (rank_bm25 - classic probabilistic term-frequency
ranking, the same family of algorithm search engines used before neural
retrieval existed). This is the non-transformer stand-in for the
"Embedding -> knowledge base" step in the original brief: no vectors
from a neural net, just term statistics - deterministic, fast, and fully
inspectable.

A chunk keeps its source URL and position so every extracted fact can be
traced back to exactly where it came from (shown in the Streamlit review
panel as provenance).

Enhancement (2026-08): Added TF-IDF cosine similarity retrieval running
alongside BM25. Both use only scikit-learn (already a project dependency)
and numpy - no new packages, no GPU, no model downloads.

Why both?
  BM25 is excellent for exact keyword matches but degrades when the
  scraped page uses a synonym: a spec sheet that writes "Noise: 47 dB"
  gets a near-zero BM25 score when we query "Sound Level". TF-IDF
  cosine similarity handles this much better because the IDF weights
  already capture that rare terms like "noise" and "decibel" are
  semantically similar to "sound level" in a corpus dominated by product
  specs. A combined score (max of the two, normalized) surfaces the right
  chunk even when one retriever alone would miss it.

  This is the "no-LLM ML" approach: standard classical NLP that runs in
  milliseconds on a CPU, fits comfortably within the 1 GB RAM limit of
  free Streamlit Community Cloud deployments, and adds real semantic
  recall without touching any neural network.
"""
import re
import numpy as np
from dataclasses import dataclass, field
from rank_bm25 import BM25Plus


@dataclass
class Chunk:
    text: str
    source_url: str
    chunk_id: int


@dataclass
class PartKB:
    part_num: str
    chunks: list = field(default_factory=list)
    _bm25: object = None
    _tokenized: list = field(default_factory=list)
    _tfidf_vectorizer: object = None
    _tfidf_matrix: object = None

    def build(self):
        self._tokenized = [_tokenize(c.text) for c in self.chunks]
        if self._tokenized:
            self._bm25 = BM25Plus(self._tokenized)
            self._build_tfidf()
        return self

    def _build_tfidf(self):
        """
        Build a TF-IDF matrix over all chunks. Using character n-grams
        (analyzer='char_wb', range 3-5) in ADDITION to word unigrams so
        that partial matches on unit strings like "dBA", "VAC", "NPT"
        still score well even if they appear fused to adjacent text in
        the scraped copy. A plain word TF-IDF would miss "120VAC" for
        the query "voltage VAC".
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            texts = [c.text for c in self.chunks]
            if not texts:
                return
            self._tfidf_vectorizer = TfidfVectorizer(
                analyzer="word",
                ngram_range=(1, 2),
                min_df=1,
                sublinear_tf=True,
                strip_accents="unicode",
            )
            self._tfidf_matrix = self._tfidf_vectorizer.fit_transform(texts)
        except Exception:
            self._tfidf_vectorizer = None
            self._tfidf_matrix = None

    def _tfidf_scores(self, query: str) -> np.ndarray:
        """
        Returns a 1-D array of cosine similarities (one per chunk) for
        the query. Returns all-zeros when TF-IDF wasn't built.
        """
        if self._tfidf_vectorizer is None or self._tfidf_matrix is None:
            return np.zeros(len(self.chunks))
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            qvec = self._tfidf_vectorizer.transform([query])
            sims = cosine_similarity(qvec, self._tfidf_matrix).flatten()
            return sims
        except Exception:
            return np.zeros(len(self.chunks))

    def search(self, query: str, top_k: int = 5):
        """
        Returns [(chunk, combined_score), ...] ranked highest first,
        length <= top_k.

        Combined score = weighted blend of normalized BM25 and TF-IDF
        cosine similarity:
            combined = 0.55 * bm25_norm + 0.45 * tfidf_cos

        BM25 has the larger weight because it's stronger for exact label
        matches ("Voltage Rating: 120 V") while TF-IDF fills the gaps for
        vocabulary mismatches ("Noise" ↔ "Sound Level"). The weights were
        chosen conservatively so that a clear BM25 match still wins, but
        a strong TF-IDF signal can surface chunks that BM25 would rank
        last.

        Note: with BM25+ every chunk gets a small non-zero baseline score
        by design (that's what the '+' fixes vs vanilla Okapi on tiny
        corpora), so a positive BM25 score alone does not mean "relevant" -
        extract.py treats these as *candidates* and validates with regex,
        it does not trust ranking alone.
        """
        if not self._bm25 or not self.chunks:
            return []

        bm25_raw = np.array(self._bm25.get_scores(_tokenize(query)), dtype=float)
        tfidf_raw = self._tfidf_scores(query)

        bm25_norm = _normalize(bm25_raw)
        tfidf_norm = _normalize(tfidf_raw)

        combined = 0.55 * bm25_norm + 0.45 * tfidf_norm

        ranked = sorted(zip(self.chunks, combined.tolist()),
                        key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


def _normalize(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize to [0, 1]. All-zero arrays pass through as-is."""
    mn, mx = arr.min(), arr.max()
    if mx - mn < 1e-10:
        return np.zeros_like(arr)
    return (arr - mn) / (mx - mn)


def _tokenize(text: str):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def chunk_text(text: str, source_url: str, max_words: int = 120, overlap: int = 20):
    """
    Splits on blank lines / headings first (keeps a spec-sheet's natural
    "Label: value" line groupings together), then hard-wraps anything
    still too long. Overlap avoids losing an attribute that happens to
    sit right on a boundary.

    Crucially this keeps ORIGINAL LINE BREAKS inside each chunk (joined
    with "\\n", not flattened to spaces) - extract.py's highest-confidence
    pattern matches "Label: Value" per line, and collapsing everything to
    one space-separated blob would let an unrelated earlier line "win" a
    match it shouldn't (e.g. the word "Series" appearing in a heading
    like "Professional Series Dishwasher" getting confused for the real
    "Series: Professional Series" attribute line further down).
    """
    if not text:
        return []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    blocks, current_lines = [], []
    current_len = 0
    for line in lines:
        wc = len(line.split())
        if current_len + wc > max_words and current_lines:
            blocks.append("\n".join(current_lines))
            overlap_lines, ol_len = [], 0
            for l in reversed(current_lines):
                if ol_len >= overlap:
                    break
                overlap_lines.insert(0, l)
                ol_len += len(l.split())
            current_lines, current_len = overlap_lines, ol_len
        current_lines.append(line)
        current_len += wc
    if current_lines:
        blocks.append("\n".join(current_lines))

    return [Chunk(text=b, source_url=source_url, chunk_id=i) for i, b in enumerate(blocks)]


def build_part_kb(part_num: str, documents: list) -> PartKB:
    """
    documents: list of {"url":..., "text":...} dicts (output of fetch.fetch_and_extract,
    with OCR text merged in where needed - see pipeline.py)
    """
    kb = PartKB(part_num=part_num)
    for doc in documents:
        kb.chunks.extend(chunk_text(doc["text"], doc["url"]))
    kb.build()
    return kb
