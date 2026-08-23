"""
cleaning.py
------------
Load the raw input (CSV or XLSX, any of the columns the brief describes)
and strip Unilog's placeholder strings ("-- Unbranded --" etc.) to real
nulls so nothing downstream treats a placeholder as a fact.
"""
import pandas as pd
from . import config


def load_input(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df.fillna("")
    df.columns = [c.strip() for c in df.columns]
    return df


def is_placeholder(value: str) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in config.PLACEHOLDER_VALUES


def clean_value(value: str) -> str:
    return "" if is_placeholder(value) else str(value).strip()


def clean_row(row: dict) -> dict:
    """Return a copy of the row with placeholder fields blanked out."""
    return {k: clean_value(v) for k, v in row.items()}


def first_non_placeholder(*values) -> str:
    for v in values:
        v = clean_value(v)
        if v:
            return v
    return ""
