import common as C
import story
import streamlit as st
import style as S

R, q, N = C.js("results.json"), C.csv("quarterly.csv"), story.numbers()
S.hero("Medical Device Quality Copilot",
       "An AI assistant that helps a quality engineer investigate medical device field failures in public FDA data. "
       "Every number it states comes from a database lookup, every claim cites a report or recall, and it remembers each investigation.",
       ["Claude Haiku 5.5", "PostgreSQL", "openFDA", "Streamlit", "pre-registered tests"])
S.cards([
    {"k": "Accuracy", "v": f"{R['phase6']['haiku_correct']}/{R['phase6']['haiku_of']}", "s": f"fixed questions, for ${R['phase6']['haiku_cost_usd']:.2f} in total", "tone": "good"},
    {"k": "FDA reports", "v": C.fmt(q["reports"].sum()), "s": f"and {C.fmt(len(C.csv('recalls.csv')))} recalls, 2022 to Nov 2026", "tone": "info"},
    {"k": "Data checks", "v": R["phase7c"]["checks"], "s": "every row rebuilt from the raw files: 0 differences", "tone": "good"},
    {"k": "Drift alert", "v": f"{N['jump']:.1f}×", "s": f"pacemaker battery reports, {N['bs_q3']:,} to {N['bs_q4']:,} in one quarter", "tone": "alert"}])
c = st.columns([1, 1, 2])
c[0].page_link("views/investigation.py", label="Follow a real investigation", icon=":material/arrow_forward:")
c[1].page_link("views/ask.py", label="Read recorded answers", icon=":material/forum:")
st.subheader("What it does")
c = st.columns(3)
with c[0], st.container(border=True):
    st.markdown("**:material/search: Investigates**  \nCounts, trends, failure modes, recalls and similar reports through eight fixed, read-only lookups. No free-form SQL.")
with c[1], st.container(border=True):
    st.markdown("**:material/fact_check: Cites and checks**  \nEvery report and recall it cites must come from its lookups; a guard reads each answer before it is shown.")
with c[2], st.container(border=True):
    st.markdown("**:material/bookmarks: Remembers**  \nWhat was ruled out, hypotheses and decisions carry over to the next session, and can be viewed, edited and deleted.")
st.subheader("Honest results")
S.scoreboard([
    {"name": "Cheap model is enough", "result": "kept Haiku", "tone": "ok", "detail": f"Opus 5.5 scored {R['phase6']['opus_correct']}/{R['phase6']['opus_of']} for ${R['phase6']['opus_cost_usd']:.2f}: no better, 40 times the cost"},
    {"name": "First safety guard", "result": f"{R['phase7']['scorecard']}, failed", "tone": "bad", "detail": "it hid half of the safe answers; the failure stays published"},
    {"name": "Replacement guard", "result": "bars met", "tone": "warn", "detail": f"{R['phase7b']['caught']} planted unsafe sentences caught; labels by an AI, no human check"}])
st.info(C.REPLAY)
st.caption(C.PHASE7)
C.footer()
