import common as C
import streamlit as st

R, q = C.js("results.json"), C.csv("quarterly.csv")
st.title("Medical Device Quality Copilot")
st.markdown("An AI assistant that helps a medical device quality engineer investigate field failures in **public FDA data**: "
            "adverse-event reports and recalls for five device types. It answers with citations, remembers each investigation, "
            "and every number it states must come from a database lookup.")
c = st.columns(4)
c[0].metric("Reports (2022 to Nov 2026)", C.fmt(q["reports"].sum()))
c[1].metric("Recalls", C.fmt(len(C.csv("recalls.csv"))))
c[2].metric("Haiku accuracy, 80 fixed questions", f"{R['phase6']['haiku_correct']}/{R['phase6']['haiku_of']}")
c[3].metric("Cost of that evaluation", f"${R['phase6']['haiku_cost_usd']:.2f}")
st.subheader("What you can do here")
st.markdown("- **Ask the copilot (recorded):** read real answers the assistant gave, with the lookups it made and what each cost.\n"
            "- **Trends and failure modes / Companies and recalls:** the data behind the answers.\n"
            "- **Drift monitoring:** what changed in 2025-2026, including a jump in pacemaker battery reports.\n"
            "- **Investigation memory:** try saving, editing and deleting investigation notes (kept in your browser session only).\n"
            "- **Evaluation and safety:** what was tested, what passed, and what failed.")
st.info(C.REPLAY)
st.warning(C.PHASE7)
C.footer()
