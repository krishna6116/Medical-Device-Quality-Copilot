"""Phase 5 investigation memory: what an investigation has established, kept across sessions.

A quality investigation runs for weeks. Memory holds its hypotheses, what was ruled out (and why), decisions
and open questions, so the next session starts where the last one stopped. Rules (config/phase5_criteria.json):
memory is written only by explicit calls (the assistant's memory tools or the user), every save is confirmed,
the user can view, edit, export and delete everything, and deletion is real: the audit trail keeps no text.

CLI:  python -m mdqc.memory list
      python -m mdqc.memory show 3
      python -m mdqc.memory export 3 [--md]
      python -m mdqc.memory delete-item 12
      python -m mdqc.memory delete 3            (the whole investigation)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("hypothesis", "ruled_out", "decision", "open_question", "note")
STATUSES = ("open", "confirmed", "rejected", "done")
CODES = ("LPH", "JWH", "MBH", "LWP", "LZG")
MAX_ITEMS, MIN_LEN, MAX_LEN = 200, 5, 500
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
MDR = re.compile(r"^(?:MDR\s*#?\s*)?(\d{7,9})$", re.I)
RECALL = re.compile(r"^Z-\d{4}-\d{4}$", re.I)

DDL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.investigation (
    investigation_id serial PRIMARY KEY,
    title text NOT NULL CHECK (length(title) BETWEEN 3 AND 200),
    product_code text CHECK (product_code IN ('LPH', 'JWH', 'MBH', 'LWP', 'LZG')),
    manufacturer text,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS {s}.session (
    session_id serial PRIMARY KEY,
    investigation_id integer NOT NULL REFERENCES {s}.investigation ON DELETE CASCADE,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz
);
CREATE TABLE IF NOT EXISTS {s}.memory_item (
    item_id serial PRIMARY KEY,
    investigation_id integer NOT NULL REFERENCES {s}.investigation ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('hypothesis', 'ruled_out', 'decision', 'open_question', 'note')),
    text text NOT NULL CHECK (length(text) BETWEEN 5 AND 500),
    evidence jsonb NOT NULL DEFAULT '[]',
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'rejected', 'done')),
    source text NOT NULL CHECK (source IN ('assistant', 'user')),
    session_id integer REFERENCES {s}.session ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS {s}.memory_event (   -- audit trail: ids, kinds, actions, times; never text
    event_id serial PRIMARY KEY,
    investigation_id integer,
    item_id integer,
    kind text,
    action text NOT NULL CHECK (action IN ('investigation_created', 'investigation_closed', 'investigation_deleted',
                                           'item_created', 'item_edited', 'item_deleted', 'session_started')),
    actor text NOT NULL CHECK (actor IN ('assistant', 'user')),
    at timestamptz NOT NULL DEFAULT now()
);
"""


class MemoryRefused(ValueError):
    """A save or change that the rules do not allow; nothing is stored."""


def ensure_schema(con, schema: str = "memory") -> None:
    con.execute(DDL.format(s=schema))
    con.commit()


def _event(con, s, action, actor, inv=None, item=None, kind=None):
    con.execute(f"INSERT INTO {s}.memory_event (investigation_id, item_id, kind, action, actor) VALUES (%s, %s, %s, %s, %s)",
                (inv, item, kind, action, actor))


def _investigation(con, s, inv, need_open=True):
    row = con.execute(f"SELECT investigation_id, title, product_code, manufacturer, status FROM {s}.investigation "
                      "WHERE investigation_id = %s", (inv,)).fetchone()
    if not row:
        raise MemoryRefused(f"investigation {inv} does not exist")
    if need_open and row[4] != "open":
        raise MemoryRefused(f"investigation {inv} is closed; reopen it before saving to it")
    return row


def check_text(text) -> str:
    text = " ".join(str(text or "").split())
    if not MIN_LEN <= len(text) <= MAX_LEN:
        raise MemoryRefused(f"memory text must be {MIN_LEN}-{MAX_LEN} characters (got {len(text)})")
    if EMAIL.search(text) or PHONE.search(text):
        raise MemoryRefused("memory must not contain personal contact details (email address or phone number)")
    return text


def check_evidence(con, evidence) -> list[dict]:
    """Every citation must be a real report key or recall number in the project data."""
    out = []
    for e in evidence or []:
        e = str(e).strip()
        m, r = MDR.match(e), RECALL.match(e)
        if m:
            ok = con.execute("SELECT 1 FROM core.fact_report WHERE mdr_report_key = %s", (m.group(1),)).fetchone()
            if not ok:
                raise MemoryRefused(f"evidence {e!r}: no such report in the project data")
            out.append({"type": "report", "id": m.group(1)})
        elif r:
            ok = con.execute("SELECT 1 FROM core.fact_recall WHERE upper(product_res_number) = upper(%s)", (e,)).fetchone()
            if not ok:
                raise MemoryRefused(f"evidence {e!r}: no such recall in the project data")
            out.append({"type": "recall", "id": e.upper()})
        else:
            raise MemoryRefused(f"evidence {e!r} must be a report key (e.g. 'MDR 16005019') or a recall number (e.g. 'Z-2155-2024')")
    return out


# ---- investigations -------------------------------------------------------------------------------------
def create_investigation(con, title, product_code=None, manufacturer=None, actor="user", schema="memory") -> int:
    title = " ".join(str(title or "").split())
    if not 3 <= len(title) <= 200:
        raise MemoryRefused("title must be 3-200 characters")
    if product_code is not None and product_code not in CODES:
        raise MemoryRefused(f"product_code must be one of {CODES}")
    inv = con.execute(f"INSERT INTO {schema}.investigation (title, product_code, manufacturer) VALUES (%s, %s, %s) "
                      "RETURNING investigation_id", (title, product_code, manufacturer)).fetchone()[0]
    _event(con, schema, "investigation_created", actor, inv)
    con.commit()
    return inv


def list_investigations(con, schema="memory") -> list[dict]:
    rows = con.execute(f"""SELECT i.investigation_id, i.title, i.product_code, i.manufacturer, i.status,
        (SELECT count(*) FROM {schema}.memory_item m WHERE m.investigation_id = i.investigation_id),
        (SELECT count(*) FROM {schema}.session x WHERE x.investigation_id = i.investigation_id)
        FROM {schema}.investigation i ORDER BY 1""").fetchall()
    return [{"investigation_id": a, "title": b, "product_code": c, "manufacturer": d, "status": e, "items": f, "sessions": g}
            for a, b, c, d, e, f, g in rows]


def close_investigation(con, inv, actor="user", schema="memory") -> None:
    _investigation(con, schema, inv)
    con.execute(f"UPDATE {schema}.investigation SET status = 'closed', updated_at = now() WHERE investigation_id = %s", (inv,))
    _event(con, schema, "investigation_closed", actor, inv)
    con.commit()


def delete_investigation(con, inv, actor="user", schema="memory") -> dict:
    """Remove the investigation, its items, sessions and audit events. One content-free event records that
    *an* investigation was deleted, without referencing it."""
    _investigation(con, schema, inv, need_open=False)
    n_items = con.execute(f"SELECT count(*) FROM {schema}.memory_item WHERE investigation_id = %s", (inv,)).fetchone()[0]
    con.execute(f"DELETE FROM {schema}.memory_event WHERE investigation_id = %s", (inv,))
    con.execute(f"DELETE FROM {schema}.investigation WHERE investigation_id = %s", (inv,))  # cascades to items, sessions
    _event(con, schema, "investigation_deleted", actor)
    con.commit()
    return {"deleted_investigation": inv, "deleted_items": n_items}


# ---- sessions ------------------------------------------------------------------------------------------------
def start_session(con, inv, actor="user", schema="memory") -> int:
    _investigation(con, schema, inv, need_open=False)
    sid = con.execute(f"INSERT INTO {schema}.session (investigation_id) VALUES (%s) RETURNING session_id", (inv,)).fetchone()[0]
    _event(con, schema, "session_started", actor, inv)
    con.commit()
    return sid


def end_session(con, sid, schema="memory") -> None:
    con.execute(f"UPDATE {schema}.session SET ended_at = now() WHERE session_id = %s", (sid,))
    con.commit()


# ---- items -----------------------------------------------------------------------------------------------------
def add_item(con, inv, kind, text, evidence=(), source="user", session_id=None, schema="memory") -> dict:
    _investigation(con, schema, inv)
    if kind not in KINDS:
        raise MemoryRefused(f"kind must be one of {KINDS}")
    text = check_text(text)
    ev = check_evidence(con, evidence)
    n = con.execute(f"SELECT count(*) FROM {schema}.memory_item WHERE investigation_id = %s", (inv,)).fetchone()[0]
    if n >= MAX_ITEMS:
        raise MemoryRefused(f"an investigation holds at most {MAX_ITEMS} items; delete or merge some first")
    item = con.execute(f"""INSERT INTO {schema}.memory_item (investigation_id, kind, text, evidence, source, session_id)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING item_id""", (inv, kind, text, json.dumps(ev), source, session_id)).fetchone()[0]
    _event(con, schema, "item_created", source, inv, item, kind)
    con.commit()
    return {"saved": True, "item_id": item, "kind": kind, "text": text, "evidence": ev,
            "confirmation": f"Saved to investigation {inv} memory as {kind} (item {item}): \"{text}\". "
                            "You can view, edit or delete it at any time."}


def edit_item(con, item_id, text=None, status=None, evidence=None, actor="user", schema="memory") -> dict:
    row = con.execute(f"SELECT investigation_id, kind FROM {schema}.memory_item WHERE item_id = %s", (item_id,)).fetchone()
    if not row:
        raise MemoryRefused(f"memory item {item_id} does not exist")
    _investigation(con, schema, row[0])
    sets, params = ["updated_at = now()"], []
    if text is not None:
        sets.append("text = %s")
        params.append(check_text(text))
    if status is not None:
        if status not in STATUSES:
            raise MemoryRefused(f"status must be one of {STATUSES}")
        sets.append("status = %s")
        params.append(status)
    if evidence is not None:
        sets.append("evidence = %s")
        params.append(json.dumps(check_evidence(con, evidence)))
    if len(sets) == 1:
        raise MemoryRefused("nothing to change: give text, status or evidence")
    con.execute(f"UPDATE {schema}.memory_item SET {', '.join(sets)} WHERE item_id = %s", params + [item_id])
    _event(con, schema, "item_edited", actor, row[0], item_id, row[1])
    con.commit()
    return {"edited": True, "item_id": item_id, "confirmation": f"Updated memory item {item_id}."}


def delete_item(con, item_id, actor="user", schema="memory") -> dict:
    row = con.execute(f"SELECT investigation_id, kind FROM {schema}.memory_item WHERE item_id = %s", (item_id,)).fetchone()
    if not row:
        raise MemoryRefused(f"memory item {item_id} does not exist")
    con.execute(f"DELETE FROM {schema}.memory_item WHERE item_id = %s", (item_id,))
    _event(con, schema, "item_deleted", actor, row[0], item_id, row[1])
    con.commit()
    return {"deleted": True, "item_id": item_id, "confirmation": f"Deleted memory item {item_id}; it is no longer stored anywhere."}


def get_items(con, inv, schema="memory") -> list[dict]:
    rows = con.execute(f"""SELECT item_id, kind, text, evidence, status, source, session_id, created_at, updated_at
        FROM {schema}.memory_item WHERE investigation_id = %s ORDER BY created_at, item_id""", (inv,)).fetchall()
    return [{"item_id": a, "kind": b, "text": c, "evidence": d, "status": e, "source": f, "session_id": g,
             "created_at": h.isoformat(), "updated_at": i.isoformat()} for a, b, c, d, e, f, g, h, i in rows]


# ---- what the assistant sees, and what the user can export -----------------------------------------------------
TITLES = {"ruled_out": "Ruled out", "hypothesis": "Hypotheses", "decision": "Decisions", "open_question": "Open questions",
          "note": "Notes"}


def memory_block(con, inv, schema="memory") -> str:
    """The text added to the system prompt at the start of a session (and returned by the recall tool)."""
    _, title, code, maker, status = _investigation(con, schema, inv, need_open=False)
    items = get_items(con, inv, schema)
    lines = [f"INVESTIGATION MEMORY (investigation {inv}: {title}; product {code or 'any'}; manufacturer {maker or 'any'}; {status})"]
    if not items:
        lines.append("Nothing saved yet.")
    for kind in ("ruled_out", "hypothesis", "decision", "open_question", "note"):
        group = [i for i in items if i["kind"] == kind]
        if group:
            lines.append(f"{TITLES[kind]}:")
            for i in group:
                ev = ", ".join(("MDR " + e["id"]) if e["type"] == "report" else e["id"] for e in i["evidence"])
                lines.append(f"- [item {i['item_id']}, {i['status']}] {i['text']}" + (f" (evidence: {ev})" if ev else ""))
    return "\n".join(lines)


def export_json(con, inv, schema="memory") -> dict:
    _, title, code, maker, status = _investigation(con, schema, inv, need_open=False)
    sessions = [{"session_id": a, "started_at": b.isoformat(), "ended_at": c.isoformat() if c else None} for a, b, c in con.execute(
        f"SELECT session_id, started_at, ended_at FROM {schema}.session WHERE investigation_id = %s ORDER BY 1", (inv,)).fetchall()]
    events = [{"event_id": a, "item_id": b, "kind": c, "action": d, "actor": e, "at": f.isoformat()} for a, b, c, d, e, f in con.execute(
        f"SELECT event_id, item_id, kind, action, actor, at FROM {schema}.memory_event WHERE investigation_id = %s ORDER BY 1", (inv,)).fetchall()]
    return {"investigation_id": inv, "title": title, "product_code": code, "manufacturer": maker, "status": status,
            "items": get_items(con, inv, schema), "sessions": sessions, "audit_trail": events,
            "note": "This is everything stored about this investigation. The audit trail holds no text."}


def export_markdown(con, inv, schema="memory") -> str:
    e = export_json(con, inv, schema)
    out = [f"# Investigation {e['investigation_id']}: {e['title']}", "",
           f"Product {e['product_code'] or 'any'}, manufacturer {e['manufacturer'] or 'any'}, status {e['status']}; "
           f"{len(e['sessions'])} sessions, {len(e['items'])} memory items.", ""]
    for kind in ("ruled_out", "hypothesis", "decision", "open_question", "note"):
        group = [i for i in e["items"] if i["kind"] == kind]
        if group:
            out += [f"## {TITLES[kind]}", ""]
            for i in group:
                ev = ", ".join(("MDR " + x["id"]) if x["type"] == "report" else x["id"] for x in i["evidence"])
                out.append(f"- **Item {i['item_id']}** ({i['status']}, by {i['source']}, {i['created_at'][:10]}): {i['text']}"
                           + (f" Evidence: {ev}." if ev else ""))
            out.append("")
    out += ["## Audit trail (no text is kept here)", ""] + [f"- {x['at'][:19]} {x['actor']} {x['action']}"
                                                           + (f" item {x['item_id']} ({x['kind']})" if x["item_id"] else "") for x in e["audit_trail"]]
    return "\n".join(out) + "\n"


def _connect():
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    con = psycopg.connect(os.environ["DATABASE_URL"])
    ensure_schema(con)
    return con


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="View, export and delete investigation memory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("show", "export", "delete"):
        p = sub.add_parser(name)
        p.add_argument("investigation_id", type=int)
        if name == "export":
            p.add_argument("--md", action="store_true")
    p = sub.add_parser("delete-item")
    p.add_argument("item_id", type=int)
    a = ap.parse_args()
    with _connect() as con:
        try:
            if a.cmd == "list":
                for inv in list_investigations(con):
                    print(f"{inv['investigation_id']}: {inv['title']} [{inv['status']}] {inv['items']} items, {inv['sessions']} sessions")
            elif a.cmd == "show":
                print(memory_block(con, a.investigation_id))
            elif a.cmd == "export":
                print(export_markdown(con, a.investigation_id) if a.md else json.dumps(export_json(con, a.investigation_id), indent=2))
            elif a.cmd == "delete":
                print(delete_investigation(con, a.investigation_id))
            elif a.cmd == "delete-item":
                print(delete_item(con, a.item_id)["confirmation"])
        except MemoryRefused as exc:
            sys.exit(f"refused: {exc}")
