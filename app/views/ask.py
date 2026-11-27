import common as C
import streamlit as st

A = C.js("answers.json")
st.title("Ask the copilot (recorded)")
st.info(C.REPLAY)
sets = sorted({a["set"] for a in A})
s = st.radio("Question set", sets, horizontal=True)
cats = ["all"] + sorted({a["category"] for a in A if a["set"] == s})
cat = st.selectbox("Kind of question", cats)
items = [a for a in A if a["set"] == s and cat in ("all", a["category"])]
pick = st.selectbox("Question", [a["id"] for a in items], format_func=lambda i: next(f"{a['id']}: {a['question']}" for a in items if a["id"] == i))
a = next(x for x in items if x["id"] == pick)
st.markdown(f"**Question:** {a['question']}")
c = st.columns(4)
c[0].container(key="model_tile").metric("Model", a["model"])  # long model name: smaller, wrapping value (CSS in style.py)
c[1].metric("Cost of this answer", f"${a['cost_usd']:.4f}")
c[2].metric("Model calls", a["steps"])
c[3].metric("Graded", "not graded" if not a["graded"] else ("correct" if a["correct"] else "wrong"))
st.caption("Lookups made: " + (", ".join(a["tools"]) if a["tools"] else "none") + (f" · recorded {a['recorded_utc']}" if a["recorded_utc"] else ""))
with st.container(border=True):
    st.markdown(a["answer"])
if a["set"].startswith("Phase 7c"):
    st.caption(C.INCOMPLETE.format(q=C.ref()["last_complete_quarter"]))
st.caption(C.ACCURACY_SCOPE)
C.footer()
