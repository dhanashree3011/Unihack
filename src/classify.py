"""
classify.py
------------
Assigns Dept / Class / Fine / Classpath. This is the one place a
non-LLM "AI/ML model" (explicitly allowed by the brief) earns its
keep: TF-IDF vectorization + Logistic Regression (both classic,
non-neural, scikit-learn) trained on whatever labeled rows are
available, since the guide references a Unicat_Lov taxonomy /
Sample_200_Items ground-truth file that determines the exact category
tree - and that file wasn't supplied.

Falls back gracefully through three tiers depending on what data IS
available, so the module never crashes or fabricates a category:

  1. self-learning cache (a human classified an item with this same
     description signature earlier in the batch)
  2. a trained TF-IDF+LogReg classifier, IF a labeled training file
     (ground_truth_200 / any CSV with Part_Desc + Classpath columns)
     is present in data/ - retrained fresh each run since the label set
     is whatever the plugged-in file contains, never hardcoded
  3. leave blank and flag for human review - per the guide, an
     empty-but-honest field beats an invented one
"""
import os
import re
import functools
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from . import config, cache_store


def _find_training_file():
    """Looks for any reference file in data/ that has description + classpath columns."""
    candidates = [
        os.path.join(config.DATA_DIR, config.OPTIONAL_REFERENCE_FILES["ground_truth_200"]),
    ]
    for fn in os.listdir(config.DATA_DIR) if os.path.isdir(config.DATA_DIR) else []:
        if fn.lower().endswith((".xlsx", ".csv")):
            candidates.append(os.path.join(config.DATA_DIR, fn))
    return [c for c in dict.fromkeys(candidates) if os.path.exists(c)]


def _load_labeled_rows():
    for path in _find_training_file():
        try:
            df = pd.read_excel(path, dtype=str) if path.endswith(".xlsx") else pd.read_csv(path, dtype=str)
        except Exception:
            continue
        df = df.fillna("")
        df.columns = [c.strip() for c in df.columns]
        desc_col = next((c for c in df.columns if c.lower() in ("part_desc", "description", "desc")), None)
        cp_col = next((c for c in df.columns if "classpath" in c.lower()), None)
        if desc_col and cp_col:
            sub = df[[desc_col, cp_col]].rename(columns={desc_col: "desc", cp_col: "classpath"})
            sub = sub[(sub["desc"] != "") & (sub["classpath"] != "")]
            if len(sub) >= 10:
                return sub
    return None


@functools.lru_cache(maxsize=1)
def _get_trained_classifier():
    rows = _load_labeled_rows()
    if rows is None or rows["classpath"].nunique() < 2:
        return None
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=5000)),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", C=20.0)),
    ])
    pipe.fit(rows["desc"], rows["classpath"])
    return pipe


def _split_classpath(classpath: str):
    """'Appliances>Kitchen Appliances>Built-In Dishwashers' -> (Dept, Class, Fine)"""
    parts = [p.strip() for p in (classpath or "").split(">") if p.strip()]
    dept = parts[0] if len(parts) > 0 else ""
    cls = parts[1] if len(parts) > 1 else ""
    fine = parts[2] if len(parts) > 2 else (parts[-1] if parts else "")
    return dept, cls, fine


def classify(part_desc: str, min_confidence: float = 0.30):
    """
    Returns {"dept","class","fine","classpath","confidence","source"} or
    None if nothing could be determined confidently.
    """
    cached = cache_store.get_classpath(part_desc)
    if cached and cached.get("classpath"):
        return {**cached, "confidence": 0.95, "source": "human_cache"}

    clf = _get_trained_classifier()
    if clf is not None and part_desc:
        proba = clf.predict_proba([part_desc])[0]
        idx = proba.argmax()
        confidence = float(proba[idx])
        if confidence >= min_confidence:
            classpath = clf.classes_[idx]
            dept, cls, fine = _split_classpath(classpath)
            return {"dept": dept, "class": cls, "fine": fine, "classpath": classpath,
                    "confidence": round(confidence, 2), "source": "tfidf_logreg"}

    return None
