"""Medical Device Quality Copilot: Phase 8 app (Streamlit). Reads only dashboards/snapshots/.

Run locally:  .venv-app\\Scripts\\streamlit run app/streamlit_app.py
"""
import importlib
import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
_mod = sys.modules.get("common")  # a running app keeps old modules; reload ours, drop a same-named one from elsewhere
if _mod is not None:
    if Path(getattr(_mod, "__file__", "") or "").resolve().parent == APP:
        importlib.reload(_mod)
    else:
        del sys.modules["common"]

import common as C  # noqa: E402

st.set_page_config(page_title="Medical Device Quality Copilot", layout="wide")
st.html("""<style>
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * { white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stMetric"]) { align-items: flex-end; }
@media (max-width: 640px) { [data-testid="stTable"] table { font-size: 0.78rem; } }
</style>""")

pages = [st.Page("views/home.py", title="Home", default=True),
         st.Page("views/ask.py", title="Ask the copilot (recorded)"),
         st.Page("views/trends.py", title="Trends and failure modes"),
         st.Page("views/companies.py", title="Companies and recalls"),
         st.Page("views/drift.py", title="Drift monitoring"),
         st.Page("views/memory.py", title="Investigation memory (sandbox)"),
         st.Page("views/evaluation.py", title="Evaluation and safety"),
         st.Page("views/about.py", title="About and limits")]
nav = st.navigation(pages)
with st.sidebar:
    st.divider()
    st.caption(f"Built by {C.AUTHOR} · [LinkedIn]({C.LINKEDIN}) · [GitHub]({C.REPO})")
    st.caption("Public FDA data (openFDA). Not medical advice.")
nav.run()
