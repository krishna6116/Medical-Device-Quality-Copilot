import altair as alt
import common as C
import pandas as pd
import story
import streamlit as st
import style as S

N = story.numbers()
last = C.ref()["last_complete_quarter"]
st.title("A real investigation: pacemaker battery reports")
st.markdown("How a quality engineer would use the copilot when the drift monitor raises an alarm. Every number below is computed from the project's data; "
            "the assistant's answers are recorded, not live.")

S.step(1, "The alarm: battery reports jump in one quarter")
b = C.csv("battery.csv")
b = b[b["quarter"] >= "2023Q1"].copy()
b["maker"] = b["company"].where(b["company"].isin(["BOSTON SCIENTIFIC", "ABBOTT"]), "OTHER")
b = b.groupby(["quarter", "maker"], as_index=False)["reports"].sum()
line = alt.Chart(b).mark_line(point=True, strokeWidth=3).encode(
    x=alt.X("quarter:N", title="Quarter received"), y=alt.Y("reports:Q", title="Battery reports"),
    color=alt.Color("maker:N", title=None, scale=alt.Scale(domain=["BOSTON SCIENTIFIC", "ABBOTT", "OTHER"], range=[S.TEAL, S.AMBER, "#9AA7B4"])),
    tooltip=["quarter", "maker", "reports"])
mark = pd.DataFrame({"quarter": ["2025Q3"], "label": ["recall starts 20 Aug 2025"], "y": [3000]})
rule = alt.Chart(mark).mark_rule(strokeDash=[5, 4], color=S.RED).encode(x="quarter:N")
note = alt.Chart(mark).mark_text(align="right", dx=-6, dy=4, color=S.RED, fontSize=12).encode(x="quarter:N", y="y:Q", text="label:N")
st.altair_chart(line + rule + note, width="stretch")
S.cards([
    {"k": "Boston Scientific, 2025Q3", "v": C.fmt(N["bs_q3"]), "s": "battery reports", "tone": "info"},
    {"k": "Boston Scientific, 2025Q4", "v": C.fmt(N["bs_q4"]), "s": f"{N['jump']:.1f} times the quarter before", "tone": "alert"},
    {"k": "Abbott, same quarters", "v": f"{N['ab_q3']:,} → {N['ab_q4']:,}", "s": "no jump: not a reporting change across the industry", "tone": "good"}])
st.caption("The drift monitor flagged pacemaker volume in 2025Q4, 2026Q1 and 2026Q2 (see Drift monitoring). " + C.INCOMPLETE.format(q=last))

S.step(2, "Which devices? Almost all from one product family")
f = C.csv("battery_brands.csv")
fam = f.groupby(["period", "family"], as_index=False)["reports"].sum()
fam["in recall"] = fam["family"].isin(story.RECALL_FAMILIES).map({True: "named in the recall", False: "other models"})
st.altair_chart(alt.Chart(fam).mark_bar().encode(x=alt.X("reports:Q", title="Boston Scientific battery reports"), y=alt.Y("family:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
                color=alt.Color("in recall:N", title=None, scale=alt.Scale(domain=["named in the recall", "other models"], range=[S.TEAL, "#B9C4CE"])),
                row=alt.Row("period:N", title=None), tooltip=["period", "family", "reports"]).properties(height=200), width="stretch")
(a1, t1), (a2, t2) = N["share"][story.BEFORE], N["share"][story.AFTER]
st.markdown(f"After the jump, **{C.pct(a2 / t2)}** of Boston Scientific's battery reports ({a2:,} of {t2:,}) were for the ACCOLADE, PROPONENT, ESSENTIO and ALTRUA families; "
            f"in the three quarters before, {C.pct(a1 / t1)} ({a1:,} of {t1:,}). Brands are read from the reports and grouped by family name.")

S.step(3, "Is there a recall? Yes, starting six weeks earlier")
S.quote(f"Recall {N['recall_first']} and {N['recall_records'] - 1} related records (event {N['recall_event']}, started 2025-08-20): {N['recall_reason']}...")
st.markdown("The recall concerns a **high battery impedance** state in the ACCOLADE family and offers a software update. "
            "Its timing and its device families line up with the jump.")

S.step(4, "What the copilot answered")
A = {a["id"]: a for a in C.js("answers.json")}
for i in ("P7c-C09", "P7c-C02"):
    a = A[i]
    with st.expander(f"{a['question']}  ·  {'correct' if a['correct'] else 'wrong'}, ${a['cost_usd']:.4f}", expanded=i == "P7c-C09"):
        st.markdown(a["answer"])
st.caption(C.REPLAY)

S.step(5, "What the data cannot tell us")
st.warning("The data cannot show that the recall caused the reports, or that devices are failing more often. A likely alternative is that the advisory led clinics to check "
           "these devices and report what they found. " + C.NOT_RATES + " The next step would be Boston Scientific's complaint data and the clinical follow-up, which are not public.")
C.footer()
