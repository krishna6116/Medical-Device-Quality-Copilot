import common as C
import streamlit as st

st.title("Companies and recalls")
code = C.pick_product("company_product")
mk = C.csv("makers.csv")
years = sorted(mk["year"].unique())
y0, y1 = st.select_slider("Years received", options=years, value=(years[0], years[-1]))
d = mk[(mk["product"] == code) & mk["year"].between(y0, y1)].groupby("company", as_index=False)["reports"].sum().sort_values(["reports", "company"], ascending=[False, True])
total = d["reports"].sum()
d["share"] = [C.pct(x / total) for x in d["reports"]]
st.subheader(f"Companies with the most reports, {y0}-{y1}: {C.product_label(code)}")
st.dataframe(d.head(10), hide_index=True, width="stretch")
st.caption(f"{C.fmt(total)} reports in total. " + C.NOT_RATES)
rc = C.csv("recalls.csv")
r = rc[rc["product"] == code].sort_values(["started", "recall_number"], ascending=[False, True])
st.subheader(f"Recalls: {C.fmt(len(r))} records in {C.fmt(r['recall_event'].nunique())} recall events (all years)")
st.dataframe(r[["recall_number", "company", "started", "status", "root_cause", "reason"]], hide_index=True, width="stretch", height=360)
st.caption("A recall record is one product in a recall event. Recalls cover all years, not only 2022-2026.")
C.footer()
