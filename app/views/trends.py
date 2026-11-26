import altair as alt
import common as C
import streamlit as st

st.title("Trends and failure modes")
code = C.pick_product("trend_product")
last = C.ref()["last_complete_quarter"]
q, m = C.csv("quarterly.csv"), C.csv("quarterly_modes.csv")
t = q[q["product"] == code].groupby("quarter", as_index=False)["reports"].sum()
t["period"] = ["incomplete" if x > last else "complete" for x in t["quarter"]]
st.subheader(f"Reports per quarter: {C.product_label(code)}")
st.altair_chart(alt.Chart(t).mark_bar().encode(x=alt.X("quarter:N", title="Quarter received"), y=alt.Y("reports:Q", title="Reports"),
                color=alt.Color("period:N", scale=alt.Scale(domain=["complete", "incomplete"], range=["#0072B2", "#BBBBBB"]), title=None),
                tooltip=["quarter", "reports"]), width="stretch")
st.caption(C.INCOMPLETE.format(q=last))
year = st.select_slider("Year", options=sorted({x[:4] for x in t["quarter"]}), value="2025")
mm = m[(m["product"] == code) & (m["quarter"].str[:4] == year)].groupby("mode", as_index=False)["reports"].sum().sort_values(["reports", "mode"], ascending=[False, True])
total = mm["reports"].sum()
mm["share"] = [C.pct(x / total) for x in mm["reports"]]
mm["meaning"] = [C.ref()["modes"][x] for x in mm["mode"]]
st.subheader(f"Failure modes in {year} ({C.fmt(total)} reports)")
st.dataframe(mm[["mode", "reports", "share", "meaning"]], hide_index=True, width="stretch")
st.caption("Failure modes come from FDA problem terms mapped by a codebook; they agreed with reference labels on about 70% of 2022-2024 test reports. "
           + C.NOT_RATES)
C.footer()
