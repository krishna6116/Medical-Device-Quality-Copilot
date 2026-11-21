"""The one text every Phase 3+ method sees for a report (so methods differ only in how they read it).

report text = all 'Description of Event or Problem' texts, then all 'Additional Manufacturer Narrative'
texts (in their original order), joined with ' || ', control characters removed (FDA's text has a few
stray 0x12 bytes), whitespace collapsed, cut to MAX_CHARS characters.
"""

from __future__ import annotations

import re

MAX_CHARS = 2000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE = re.compile(r"\s+")
ORDER = {"Description of Event or Problem": 0, "Additional Manufacturer Narrative": 1}


def normalise(text: str) -> str:
    return _SPACE.sub(" ", _CONTROL.sub(" ", text or "")).strip()


def report_text(parts: list[tuple[int, str | None, str]]) -> str:
    """parts = [(text_seq, text_type, text), ...] for one report."""
    ordered = sorted(parts, key=lambda p: (ORDER.get(p[1] or "", 2), p[0]))
    joined = " || ".join(t for t in (normalise(p[2]) for p in ordered) if t)
    return joined[:MAX_CHARS]


SQL_TEXTS = """SELECT r.mdr_report_key, r.product_code, t.text_seq, t.text_type, t.text
               FROM {s}.fact_report r JOIN {s}.report_text t USING (mdr_report_key)"""


def load_texts(con, schema: str = "core", keys: list[str] | None = None) -> dict[str, str]:
    """mdr_report_key -> report text, for all reports or the given keys."""
    q = SQL_TEXTS.format(s=schema) + (" WHERE r.mdr_report_key = ANY(%s)" if keys is not None else "")
    parts: dict[str, list] = {}
    for key, _code, seq, ttype, text in con.execute(q, (keys,) if keys is not None else ()).fetchall():
        parts.setdefault(key, []).append((seq, ttype, text))
    return {k: report_text(v) for k, v in parts.items()}
