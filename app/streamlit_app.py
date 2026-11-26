"""Medical Device Quality Copilot: the app (Streamlit). Reads only dashboards/snapshots/.

Run locally:  .venv-app\\Scripts\\streamlit run app/streamlit_app.py
"""
import importlib
import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
for _name in ("common", "style"):  # a running app keeps old modules; reload ours, drop same-named ones from elsewhere
    _mod = sys.modules.get(_name)
    if _mod is not None:
        if Path(getattr(_mod, "__file__", "") or "").resolve().parent == APP:
            importlib.reload(_mod)
        else:
            del sys.modules[_name]

import common as C  # noqa: E402
import style as S  # noqa: E402

st.set_page_config(page_title="Medical Device Quality Copilot", page_icon=":material/medical_services:", layout="wide")
S.css()

pages = {"Overview": [st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
                      st.Page("views/investigation.py", title="A real investigation", icon=":material/search_insights:"),
                      st.Page("views/how.py", title="How it works", icon=":material/account_tree:")],
         "Explore": [st.Page("views/ask.py", title="Ask the copilot (recorded)", icon=":material/forum:"),
                     st.Page("views/trends.py", title="Trends and failure modes", icon=":material/monitoring:"),
                     st.Page("views/companies.py", title="Companies and recalls", icon=":material/factory:"),
                     st.Page("views/drift.py", title="Drift monitoring", icon=":material/notifications_active:"),
                     st.Page("views/memory.py", title="Investigation memory (sandbox)", icon=":material/bookmarks:")],
         "Trust": [st.Page("views/evaluation.py", title="Evaluation and safety", icon=":material/verified:"),
                   st.Page("views/about.py", title="About and limits", icon=":material/info:")]}
nav = st.navigation(pages)
with st.sidebar:
    st.caption(f"Built by **{C.AUTHOR}**  \n[LinkedIn]({C.LINKEDIN}) · [GitHub]({C.REPO})")
    st.caption("Public FDA data (openFDA). Not medical advice.")
nav.run()
