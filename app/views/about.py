import common as C
import streamlit as st

st.title("About and limits")
st.markdown(f"""**What it is:** a portfolio project by {C.AUTHOR}. Source, tests and every result: [GitHub]({C.REPO}).
The companion project, predictive maintenance with OEE, is [here]({C.PREDICTIVE_APP}).

**How it works:** openFDA reports and recalls for five device types (uncemented hips, cemented and uncemented knees, pacemakers, insulin pumps) are loaded into
PostgreSQL and checked row by row. Failure modes come from FDA problem terms. The assistant (Claude Haiku 5.5) can only use eight fixed, read-only lookups,
must cite report and recall numbers, and keeps memory per investigation. Every phase was planned and its pass marks committed before results existed,
and each has an independent verifier that runs in continuous integration.""")
st.subheader("Limits")
st.markdown("\n".join(f"- {x}" for x in [
    C.NOT_RATES, "A report says a device may have been involved; it does not prove the device caused the event.",
    C.INCOMPLETE.format(q=C.ref()["last_complete_quarter"]), C.ACCURACY_SCOPE, C.PHASE7, C.PHASE7B,
    "Failure modes agree with reference labels on about 70% of test reports, and were not re-checked on 2025-2026.",
    "2022-2024 reports come from an FDA snapshot of 21 November 2026, later reports from 25 November 2026.",
    "No live model runs here: " + C.REPLAY.split(": ", 1)[1]]))
st.subheader("Snapshot")
st.markdown(f"Data checksum: `{C.manifest()['data_checksum']}`")
st.caption("Not medical advice. For any decision about a device, ask a clinician and the manufacturer.")
