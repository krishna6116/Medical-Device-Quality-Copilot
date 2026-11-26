import common as C
import streamlit as st

st.title("Investigation memory (sandbox)")
st.markdown("In the real tool, each investigation keeps what has been concluded (ruled out, hypotheses, decisions, open questions) so the next session "
            "starts where the last one stopped. Here you can try it: **your notes live only in this browser session** and disappear when you close the tab.")
KINDS = ["ruled_out", "hypothesis", "decision", "open_question", "note"]
if "memory" not in st.session_state:
    st.session_state.memory = [{"id": 1, "kind": "ruled_out", "text": "Rising adhesive failures ruled out for Insulet pods, 2022-2024 (down 4.4%).", "status": "open"},
                               {"id": 2, "kind": "open_question", "text": "Do pacemaker battery reports from 2025Q4 come from one model family?", "status": "open"}]
mem = st.session_state.memory
with st.form("add", clear_on_submit=True):
    kind = st.selectbox("Kind", KINDS)
    text = st.text_input("What should the investigation remember?")
    if st.form_submit_button("Save"):
        text = (text or "").strip()
        if not 5 <= len(text) <= 500:
            st.error("Not saved: a note needs 5 to 500 characters.")
        elif C.personal(text):
            st.error("Not saved: notes cannot contain phone numbers or e-mail addresses (personal data).")
        elif len(mem) >= 200:
            st.error("Not saved: an investigation keeps at most 200 notes.")
        else:
            mem.append({"id": max([m["id"] for m in mem] or [0]) + 1, "kind": kind, "text": text, "status": "open"})
            st.success(f"Saved as {kind}. You can view, mark done or delete it below.")
st.subheader(f"Saved notes ({len(mem)})")
for m in list(mem):
    c = st.columns([6, 1, 1])
    c[0].markdown(f"**{m['kind']}** ({m['status']}): {m['text']}")
    if c[1].button("Done", key=f"done{m['id']}", disabled=m["status"] == "done"):
        m["status"] = "done"
        st.rerun()
    if c[2].button("Delete", key=f"del{m['id']}"):
        mem.remove(m)
        st.rerun()
st.download_button("Export as Markdown", "\n".join(f"- {m['kind']} ({m['status']}): {m['text']}" for m in mem) or "Nothing saved.", file_name="investigation.md")
st.caption("The real tool also refuses evidence that does not exist in the database and keeps an audit trail that stores no text; deletion removes the note everywhere.")
C.footer()
