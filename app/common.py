"""Shared helpers for the Streamlit app. Reads only dashboards/snapshots/ (no database, no API, no key)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

SNAP = Path(__file__).resolve().parents[1] / "dashboards" / "snapshots"
REPO = "https://github.com/krishna6116/Medical-Device-Quality-Copilot"
LINKEDIN = "https://www.linkedin.com/in/krishnakumar-balasundaram-3a92b6422"
AUTHOR = "Krishnakumar Balasundaram"
PREDICTIVE_APP = "https://predictive-maintenance-oee.streamlit.app"

# Sentences shown on the pages; the verifier checks they are present, so wording changes go through it.
REPLAY = "These are recorded answers, replayed: nothing here calls a model, and the app has no API key."
INCOMPLETE = "Reports after {q} are still arriving, so the latest quarter looks lower than it will be."
NOT_RATES = "Report counts are not failure rates: there is no count of devices in use, and larger companies report more."
ACCURACY_SCOPE = "Accuracy was measured on 2022-2024 reports; the 2025-2026 data was checked with 20 questions only."
PHASE7 = "The first safety guard failed its red-team test, so Phase 7 scored 4/5; that result stays published."
PHASE7B = "The replacement guard (Phase 7b) met its pre-set bars, but its test labels came from an AI, not a person."


@st.cache_data
def csv(name: str) -> pd.DataFrame:
    return pd.read_csv(SNAP / name, keep_default_na=False, na_values=[""])


@st.cache_data
def js(name: str):
    return json.loads((SNAP / name).read_text(encoding="utf-8"))


def ref() -> dict:
    return js("reference.json")


def manifest() -> dict:
    return js("manifest.json")


def product_label(code: str) -> str:
    return f"{ref()['products'][code]} ({code})"


def pick_product(key: str, default: str = "LWP") -> str:
    codes = list(ref()["products"])
    return st.selectbox("Device type", codes, index=codes.index(default), format_func=product_label, key=key)


def fmt(n) -> str:
    return f"{int(n):,}"


def pct(x: float, places: int = 1) -> str:
    return f"{100 * x:.{places}f}%"


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")


def personal(text: str) -> bool:
    return bool(EMAIL.search(text or "") or PHONE.search(text or ""))


def footer() -> None:
    st.caption(f"Data: openFDA MAUDE adverse-event reports and recalls (public). Snapshot `{manifest()['data_checksum'][:12]}`. "
               "Not medical advice: for any device decision, ask a clinician and the manufacturer.")
