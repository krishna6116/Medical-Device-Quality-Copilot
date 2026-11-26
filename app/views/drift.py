import altair as alt
import common as C
import streamlit as st

st.title("Drift monitoring")
st.markdown("Each quarter of 2025-2026 is compared with the same device type's previous four quarters on three measures. "
            "A flag means the change is larger than all but one of 40 normal quarters in 2023-2024: a prompt to look closer, not proof of a problem.")
d, thr = C.csv("drift.csv"), C.ref()["drift_thresholds"]
flags = d[d["flags"].fillna("") != ""]
c = st.columns(3)
c[0].metric("Checks", C.fmt(len(d) * 3))
c[1].metric("Flags", C.fmt(sum(len(f.split(";")) for f in flags["flags"])))
c[2].metric("Quarters flagged", C.fmt(len(flags)))
st.subheader("Flagged quarters")
show = flags.assign(volume_change=[f"{100 * x:+.1f}%" for x in flags["volume_change"]], mode_mix=[f"{x:.3f}" for x in flags["mode_mix"]],
                    flags=[f.replace(";", ", ") for f in flags["flags"]])
st.dataframe(show[["product", "quarter", "reports", "volume_change", "mode_mix", "flags", "largest_mode_move"]], hide_index=True, width="stretch")
st.caption(f"Limits: volume change {thr['volume']:.3f}, failure-mode mix {thr['mode_mix']:.3f}, vocabulary {thr['vocabulary']:.3f}. "
           "The vocabulary check could not detect even a large planted change, and a lasting shift stops being flagged after about a year.")
st.subheader("Pacemaker battery reports per quarter (all companies)")
m = C.csv("quarterly_modes.csv")
b = m[(m["product"] == "LWP") & (m["mode"] == "C_BATTERY")]
st.altair_chart(alt.Chart(b).mark_line(point=True).encode(x=alt.X("quarter:N", title="Quarter received"), y=alt.Y("reports:Q", title="Battery reports"),
                tooltip=["quarter", "reports"]), width="stretch")
st.caption("Battery reports rose sharply from 2025Q4, almost all from one company. The data does not say why (a recall, bulk reporting or a real change are all possible). "
           + C.INCOMPLETE.format(q=C.ref()["last_complete_quarter"]))
C.footer()
