import common as C
import streamlit as st
import style as S

R, q = C.js("results.json"), C.csv("quarterly.csv")
st.title("How it works")
st.graphviz_chart("""digraph {
  rankdir=LR; bgcolor="transparent"; node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=13 color="#C9D6E0" fillcolor="#F2F6F9" fontcolor="#16212E"];
  edge [color="#8CA3B5"];
  fda [label="openFDA\\nreports + recalls"]; db [label="PostgreSQL\\nchecked row by row"]; modes [label="Failure modes\\n+ drift signals"];
  tools [label="8 fixed lookups\\n(read-only)"]; llm [label="Claude Haiku 5.5\\ncites every number" fillcolor="#0E6E8C" fontcolor="white" color="#0E6E8C"];
  guard [label="Safety guard\\nquotes its reason"]; mem [label="Investigation\\nmemory"]; you [label="Quality engineer"];
  fda -> db -> modes -> tools; db -> tools; tools -> llm; mem -> llm; llm -> mem; llm -> guard -> you; you -> llm;
}""", width="stretch")
steps = [("Data", f"{C.fmt(q['reports'].sum())} openFDA reports and {C.fmt(len(C.csv('recalls.csv')))} recalls for five device types, loaded into PostgreSQL; "
                  "every row is rebuilt from the raw files by separate code and must match."),
         ("Failure modes", "FDA problem terms are mapped to device-specific failure modes; this simple method beat text-based ones on hand-labelled reports (about 70% agreement)."),
         ("Lookups", "The model never writes SQL: it can only call eight fixed, read-only lookups, and the database refuses writes while they run."),
         ("Answers", f"Claude Haiku 5.5 must cite reports and recalls from its lookups. On 80 fixed questions it scored {R['phase6']['haiku_correct']}/{R['phase6']['haiku_of']} "
                     f"for ${R['phase6']['haiku_cost_usd']:.2f}; Claude Opus 5.5 was no better."),
         ("Safety", "A guard reads each answer for medical advice, causal claims and identifying people. " + C.PHASE7 + " " + C.PHASE7B),
         ("Memory", "Each investigation remembers what was ruled out, hypotheses and decisions; nothing personal is stored and deletion is real."),
         ("Monitoring", "New FDA reports are compared quarter by quarter; the drift check found the pacemaker battery jump in 2025Q4.")]
for i, (t, d) in enumerate(steps, 1):
    S.step(i, t)
    st.markdown(d)
st.caption("Every phase was planned, and its pass marks committed, before results existed; each has an independent check that runs in continuous integration.")
C.footer()
