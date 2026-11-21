"""Phase 3 failure-mode methods M1-M5, exactly as registered in config/phase3_criteria.json.

Every method returns one mode per report from config/failure_modes.json. Methods differ only in what
they read: M1 the FDA problem terms, M2 keyword rules on the text, M3 text embeddings vs. mode
definitions, M4 = M2 when a keyword matches else M3, M5 unsupervised clusters named from validation labels.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CODEBOOK = json.loads((ROOT / "config" / "failure_modes.json").read_text(encoding="utf-8"))
FAMILY_OF = {c: f for f, v in CODEBOOK["families"].items() for c in v["codes"]}
METHOD_ORDER = ["M1", "M2", "M3", "M4", "M5"]  # tie-break: simpler first


def family(code: str) -> str:
    return FAMILY_OF[code]


def other(fam: str) -> str:
    return next(m for m in CODEBOOK["families"][fam]["modes"] if m.endswith("_OTHER"))


def priority(fam: str) -> list[str]:
    return CODEBOOK["families"][fam]["priority"]


@lru_cache(maxsize=None)
def _patterns(fam: str) -> dict[str, re.Pattern]:
    return {m: re.compile(d["keywords"], re.IGNORECASE)
            for m, d in CODEBOOK["families"][fam]["modes"].items() if "keywords" in d}


# ---- M1: FDA problem terms -------------------------------------------------------------------------
def m1(fam: str, device_terms: list[str], patient_terms: list[str]) -> str:
    tmap = CODEBOOK["fda_term_map"][fam]
    found = {tmap[t] for t in device_terms if t in tmap} | {tmap["patient:" + t] for t in patient_terms
                                                             if "patient:" + t in tmap}
    for mode in priority(fam):
        if mode in found:
            return mode
    return other(fam)


# ---- M2: keyword rules ----------------------------------------------------------------------------
def keyword_hits(fam: str, text: str) -> dict[str, int]:
    """mode -> position of its first keyword match in the text (only modes that match)."""
    hits = {}
    for mode, pat in _patterns(fam).items():
        m = pat.search(text)
        if m:
            hits[mode] = m.start()
    return hits


def m2(fam: str, text: str, setting: str) -> str:
    hits = keyword_hits(fam, text)
    if not hits:
        return other(fam)
    if setting == "earliest":
        order = {m: i for i, m in enumerate(priority(fam))}
        return min(hits, key=lambda m: (hits[m], order[m]))
    if setting == "priority":
        return next(m for m in priority(fam) if m in hits)
    raise ValueError(setting)


# ---- M3: embeddings vs mode definitions --------------------------------------------------------------
def mode_definitions(fam: str) -> tuple[list[str], list[str]]:
    """Modes that have a definition to compare with (the *_OTHER mode is the fallback, not a target)."""
    modes = [m for m in CODEBOOK["families"][fam]["modes"] if not m.endswith("_OTHER")]
    return modes, [CODEBOOK["families"][fam]["modes"][m]["definition"] for m in modes]


def m3(fam: str, report_vec: np.ndarray, def_vecs: np.ndarray, modes: list[str], threshold: float | None) -> str:
    sims = def_vecs @ report_vec
    best = int(np.argmax(sims))
    if threshold is not None and sims[best] < threshold:
        return other(fam)
    return modes[best]


def m3_scores(report_vec: np.ndarray, def_vecs: np.ndarray) -> np.ndarray:
    return def_vecs @ report_vec


# ---- M4: hybrid --------------------------------------------------------------------------------------
def m4(fam: str, text: str, m2_setting: str, m3_label: str) -> str:
    return m2(fam, text, m2_setting) if keyword_hits(fam, text) else m3_label


# ---- M5: TF-IDF + k-means per family -----------------------------------------------------------------
def m5_clusters(texts: dict[str, str], codes: dict[str, str]) -> dict[str, int]:
    """key -> cluster id (unique across families: family index * 100 + cluster)."""
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    out = {}
    for fi, fam in enumerate(CODEBOOK["families"]):
        keys = sorted(k for k in texts if family(codes[k]) == fam)
        k = len(CODEBOOK["families"][fam]["modes"])
        X = TfidfVectorizer(ngram_range=(1, 2), min_df=5, stop_words="english").fit_transform([texts[x] for x in keys])
        labels = KMeans(n_clusters=k, random_state=0, n_init=10).fit_predict(X)
        out.update({key: fi * 100 + int(c) for key, c in zip(keys, labels)})
    return out


def m5_names(cluster_of: dict[str, int], validation_labels: dict[str, str], codes: dict[str, str]) -> dict[int, str]:
    """Name each cluster by the majority validation label in it (ties -> family priority order)."""
    from collections import Counter

    votes: dict[int, Counter] = {}
    for key, lab in validation_labels.items():
        votes.setdefault(cluster_of[key], Counter())[lab] += 1
    names = {}
    for cl in set(cluster_of.values()):
        fam = list(CODEBOOK["families"])[cl // 100]
        if cl not in votes:
            names[cl] = other(fam)
            continue
        top = max(votes[cl].values())
        tied = [m for m, n in votes[cl].items() if n == top]
        order = priority(fam) + [other(fam)]
        names[cl] = min(tied, key=order.index)
    return names
