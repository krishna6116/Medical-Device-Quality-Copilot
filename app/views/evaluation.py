import common as C
import pandas as pd
import streamlit as st

R = C.js("results.json")
p6, p7, b, c7 = R["phase6"], R["phase7"], R["phase7b"], R["phase7c"]
st.title("Evaluation and safety")
st.subheader("Accuracy: 80 questions fixed before any model answered")
c = st.columns(3)
c[0].metric("Claude Haiku 5.5", f"{p6['haiku_correct']}/{p6['haiku_of']}", f"${p6['haiku_cost_usd']:.2f}", delta_color="off")
c[1].metric("Claude Opus 5.5", f"{p6['opus_correct']}/{p6['opus_of']}", f"${p6['opus_cost_usd']:.2f}", delta_color="off")
c[2].metric("Opus minus Haiku (95% interval)", f"{100 * p6['difference']:+.1f} points", f"{100 * p6['ci95'][0]:+.1f} to {100 * p6['ci95'][1]:+.1f}", delta_color="off")
st.markdown(f"**Decision (rule fixed in advance):** {p6['decision']}")
st.caption("All six wrong answers were read: each looked like a correct answer the strict text rules did not recognise. " + C.ACCURACY_SCOPE)
st.subheader("Safety: red-team test (Phase 7)")
st.warning(C.PHASE7)
rows = [{"category": k, "assistant's own answers": f"{v['raw']}/{v['of']}", "withheld by the guard": v["withheld"], "passes as shown": f"{v['shown']}/{v['of']}", "needed": v["needed"]}
        for k, v in p7["categories"].items()]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
st.caption(f"The guard withheld {p7['withheld']} of {p7['cases']} answers that had been labelled safe. Labels were made by Claude, not independently.")
st.subheader("A replacement guard (Phase 7b)")
st.info(C.PHASE7B)
c = st.columns(3)
c[0].metric("Planted unsafe sentences caught", b["caught"])
c[1].metric("Clean answers withheld", f"{b['clean_withheld']}/40")
c[2].metric("Planted items the labeller called unsafe", b["plants_labelled_unsafe"])
st.subheader("Reports from 2025-2026 (Phase 7c)")
c = st.columns(3)
c[0].metric("Independent data checks", c7["checks"])
c[1].metric("Questions answered correctly", c7["correct"])
c[2].metric("Cost", f"${c7['cost_usd']:.3f}")
C.footer()
