"""Phase 5 independent verification (criteria M1-M5 in config/phase5_criteria.json).

Run:  python -m mdqc.verify_phase5             full (needs the database); writes evidence
      python -m mdqc.verify_phase5 --offline   CI: what the committed recordings allow (M2 model replay, M5 replay)

Independence: it never asks mdqc.memory what memory *should* contain. It replays every recorded save, edit and
deletion in a plain-Python model, renders the memory block with its own code, and compares that with what each
session actually received and with what the database finally holds. Deletion is checked by scanning every text
and jsonb column of every table in the scenario schema. Guardrails are probed through the API as a black box.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "phase5"
ORDER = [("ruled_out", "Ruled out"), ("hypothesis", "Hypotheses"), ("decision", "Decisions"),
         ("open_question", "Open questions"), ("note", "Notes")]


def render(inv, meta, items) -> str:
    """Own rendering of the memory block, written from the format spec, not imported."""
    lines = [f"INVESTIGATION MEMORY (investigation {inv}: {meta['title']}; product {meta['product_code'] or 'any'}; "
             f"manufacturer {meta['manufacturer'] or 'any'}; open)"]
    mine = sorted((i for i in items.values() if i["inv"] == inv), key=lambda i: i["id"])
    if not mine:
        lines.append("Nothing saved yet.")
    for kind, title in ORDER:
        group = [i for i in mine if i["kind"] == kind]
        if group:
            lines.append(f"{title}:")
            for i in group:
                ev = ", ".join(("MDR " + e["id"]) if e["type"] == "report" else e["id"] for e in i["evidence"])
                lines.append(f"- [item {i['id']}, {i['status']}] {i['text']}" + (f" (evidence: {ev})" if ev else ""))
    return "\n".join(lines)


def model(log):
    """Replay the log: returns (expected block per session, final items, deleted texts, deleted ids, deleted invs)."""
    metas, items, deleted_texts, deleted_ids, deleted_invs, expected = {}, {}, [], [], [], []
    for e in log:
        if e["type"] == "create":
            metas[e["investigation_id"]] = e
        elif e["type"] == "session":
            expected.append(render(e["investigation_id"], metas[e["investigation_id"]], items))
            for t in e["tool_calls"]:
                r = json.loads(t["result"])
                if t["is_error"]:
                    continue
                if t["name"] == "remember":
                    items[r["item_id"]] = {"id": r["item_id"], "inv": e["investigation_id"], "kind": r["kind"], "text": r["text"],
                                           "evidence": r["evidence"], "status": "open"}
                elif t["name"] == "update_memory":
                    i = items[t["input"]["item_id"]]
                    i["text"] = t["input"].get("text", i["text"])
                    i["status"] = t["input"].get("status", i["status"])
                elif t["name"] == "forget":
                    gone = items.pop(t["input"]["item_id"])
                    deleted_texts.append(gone["text"])
                    deleted_ids.append(gone["id"])
        elif e["type"] == "user":
            if e["action"] == "edit":
                i = items[e["args"]["item_id"]]
                i["text"] = " ".join(e["args"]["text"].split()) if e["args"].get("text") else i["text"]
                i["status"] = e["args"].get("status") or i["status"]
            elif e["action"] == "delete":
                gone = items.pop(e["args"]["item_id"])
                deleted_texts.append(gone["text"])
                deleted_ids.append(gone["id"])
            elif e["action"] == "delete_investigation":
                inv = e["args"]["inv"]
                for k in [k for k, v in items.items() if v["inv"] == inv]:
                    deleted_texts.append(items[k]["text"])
                    deleted_ids.append(k)
                    del items[k]
                deleted_invs.append(inv)
    return expected, items, deleted_texts, deleted_ids, deleted_invs


def scan(con, schema, texts):
    """Search every text/jsonb column of every table in `schema` for each text AND its first and last 30
    characters (so a partial copy is caught too). Returns (columns, patterns, hits)."""
    cols = con.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
        WHERE table_schema = %s AND data_type IN ('text', 'jsonb', 'character varying')""", (schema,)).fetchall()
    needles = sorted({n for t in texts for n in (t, t[:30], t[-30:]) if len(n) >= 12})
    hits = []
    for needle in needles:
        for table, col, _ in cols:
            n = con.execute(f'SELECT count(*) FROM {schema}.{table} WHERE "{col}"::text ILIKE %s',
                            ("%" + needle.replace("%", "\\%").replace("_", "\\_") + "%",)).fetchone()[0]
            if n:
                hits.append((needle[:40], table, col, n))
    return cols, needles, hits


def replay(calls):
    tool_calls, answer = [], ""
    for c in calls:
        content = c["response"]["content"]
        if c["stop_reason"] == "tool_use":
            tool_calls += [(b["name"], json.dumps(b["input"], sort_keys=True)) for b in content if b["type"] == "tool_use"]
        else:
            answer = "\n".join(b["text"] for b in content if b["type"] == "text").strip()
    return tool_calls, answer


def main(offline: bool, evidence: Path | None) -> int:
    checks = []

    def check(cid, name, ok, detail):
        checks.append({"id": cid, "check": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {cid} {name}: {json.dumps(detail, default=str)[:260]}")

    sc = json.loads((RES / "scenarios.json").read_text(encoding="utf-8"))
    log, S = sc["log"], sc["schema"]
    sessions = [e for e in log if e["type"] == "session"]
    expected, final, deleted_texts, deleted_ids, deleted_invs = model(log)
    refused_texts = [t["input"].get("text", "") for e in sessions for t in e["tool_calls"] if t["name"] == "remember" and t["is_error"]]

    if not offline:
        tests = subprocess.run([sys.executable, "-m", "pytest", "tests/test_phase5.py"], cwd=ROOT, capture_output=True, text=True)
        last = (tests.stdout.strip().splitlines() or [""])[-1]
        check("M1", "memory API round trips, constraints and survival of a data reload (tests on PostgreSQL)",
              tests.returncode == 0 and "passed" in last and "skipped" not in last, {"pytest": last})

    blocks_ok = [a == b["memory_block"] for a, b in zip(expected, sessions)]
    m2_detail = {"sessions": len(sessions), "blocks_matching_model": sum(blocks_ok),
                 "mismatch_sessions": [i for i, ok in enumerate(blocks_ok) if not ok]}
    final_ok = True
    if not offline:
        import psycopg
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        con = psycopg.connect(os.environ["DATABASE_URL"])
        db_items = {r[0]: {"id": r[0], "inv": r[1], "kind": r[2], "text": r[3], "evidence": r[4], "status": r[5]} for r in con.execute(
            f"SELECT item_id, investigation_id, kind, text, evidence, status FROM {S}.memory_item").fetchall()}
        final_ok = db_items == final
        m2_detail["final_database_equals_model"] = final_ok
    check("M2", "each session's memory block = independent replay of all saves/edits/deletes; final DB = model",
          all(blocks_ok) and len(blocks_ok) == len(sessions) and final_ok, m2_detail)

    if not offline:
        cols, needles, hits = scan(con, S, deleted_texts + refused_texts)
        # self-test: the scanner must catch a planted partial copy of a deleted text (a check that cannot fail proves nothing)
        from mdqc import memory as mem
        T = "verify_memory_plant"
        con.execute(f"DROP SCHEMA IF EXISTS {T} CASCADE")
        mem.ensure_schema(con, T)
        pinv = mem.create_investigation(con, "plant test", "LZG", schema=T)
        secret = "Planted sentence that must vanish after deletion, word for word."
        mem.delete_item(con, mem.add_item(con, pinv, "note", secret, schema=T)["item_id"], schema=T)
        clean = not scan(con, T, [secret])[2]
        con.execute(f"UPDATE {T}.investigation SET manufacturer = %s WHERE investigation_id = %s", (secret[:35], pinv))
        caught = bool(scan(con, T, [secret])[2])
        con.execute(f"DROP SCHEMA {T} CASCADE")
        con.commit()
        ids_left = con.execute(f"SELECT count(*) FROM {S}.memory_item WHERE item_id = ANY(%s)", (deleted_ids,)).fetchone()[0]
        inv_refs = sum(con.execute(f"SELECT count(*) FROM {S}.{t} WHERE investigation_id = ANY(%s)", (deleted_invs,)).fetchone()[0]
                       for t in ("investigation", "session", "memory_item", "memory_event"))
        event_cols = sorted(c for t, c, _ in cols if t == "memory_event")
        audit_ok = set(event_cols) <= {"kind", "action", "actor"}
        check("M3", "deleted and refused texts appear in no column of any memory table; ids and investigations gone; audit holds no text; scanner catches a planted copy",
              not hits and ids_left == 0 and inv_refs == 0 and audit_ok and clean and caught,
              {"scanner_self_test": {"clean_after_delete": clean, "planted_partial_copy_caught": caught},
               "texts_scanned": len(deleted_texts + refused_texts), "patterns_scanned": len(needles), "columns_scanned": len(cols), "hits": hits,
               "deleted_ids_left": ids_left, "rows_referencing_deleted_investigations": inv_refs, "audit_text_columns": event_cols})

    # M4: refusals in the scenarios + a black-box probe of the API in a scratch schema
    scenario_refusals = {
        "invented evidence refused": any("no such report" in json.loads(t["result"]).get("error", "") for e in sessions for t in e["tool_calls"]),
        "phone number refused": any("personal contact" in json.loads(t["result"]).get("error", "") for e in sessions for t in e["tool_calls"]),
        "cross-investigation forget refused": any(t["name"] == "forget" and t["is_error"] for e in sessions for t in e["tool_calls"]),
        "every save confirmed in the answer": all(json.loads(t["result"])["confirmation"] in e["answer"] for e in sessions
                                                  for t in e["tool_calls"] if t["name"] == "remember" and not t["is_error"]),
    }
    probe = {}
    if not offline:
        from mdqc import memory as mem
        P = "verify_memory_probe"
        con.execute(f"DROP SCHEMA IF EXISTS {P} CASCADE")
        mem.ensure_schema(con, P)
        inv = mem.create_investigation(con, "probe investigation", "LZG", schema=P)
        closed = mem.create_investigation(con, "closed probe", "LZG", schema=P)
        mem.close_investigation(con, closed, schema=P)
        key = con.execute("SELECT mdr_report_key FROM core.fact_report WHERE product_code = 'LZG' ORDER BY 1 LIMIT 1").fetchone()[0]
        cases = {"invented report": (inv, "note", "valid text here", ["MDR 99999999"]),
                 "invented recall": (inv, "note", "valid text here", ["Z-9999-2099"]),
                 "malformed evidence": (inv, "note", "valid text here", ["see the report"]),
                 "email": (inv, "note", "write to someone at qa.person@example.com", []),
                 "phone": (inv, "note", "call (555) 123-4567 tomorrow", []),
                 "empty": (inv, "note", "   ", []), "too long": (inv, "note", "x" * 501, []),
                 "wrong kind": (inv, "rumour", "valid text here", []),
                 "closed investigation": (closed, "note", "valid text here", []), "missing investigation": (99999, "note", "valid text here", [])}
        for name, (i, kind, text, ev) in cases.items():
            try:
                mem.add_item(con, i, kind, text, ev, schema=P)
                probe[name] = "STORED (bad)"
            except mem.MemoryRefused:
                con.rollback()
                probe[name] = "refused"
        good = mem.add_item(con, inv, "note", "Valid note citing a real report.", [f"MDR {key}"], schema=P)
        stored = con.execute(f"SELECT count(*) FROM {P}.memory_item").fetchone()[0]
        probe["valid save confirmed"] = "Saved to investigation" in good["confirmation"]
        probe["only the valid item stored"] = stored == 1
        con.execute(f"DROP SCHEMA {P} CASCADE")
        con.commit()
    check("M4", "invented evidence, personal data, bad text/kind, closed/missing investigation refused; saves confirmed",
          all(scenario_refusals.values()) and (offline or (all(v == "refused" for k, v in probe.items() if isinstance(v, str))
                                                          and probe["valid save confirmed"] and probe["only the valid item stored"])),
          {"scenarios": scenario_refusals, "api_probe": probe})

    rep_bad = []
    for e in sessions:
        tc, ans = replay(e["calls"])
        if tc != [(t["name"], json.dumps(t["input"], sort_keys=True)) for t in e["tool_calls"]] or ans != e["answer"]:
            rep_bad.append(e["question"][:40])
    exp = sc["export_S_B"]
    md = (RES / "export_S_B.md").read_text(encoding="utf-8")
    md_ok = all(i["text"] in md for i in exp["items"])
    export_ok = md_ok
    if not offline:
        inv_b = exp["investigation_id"]
        db_b = [(r[0], r[1], r[2], r[3], r[4]) for r in con.execute(
            f"SELECT item_id, kind, text, evidence, status FROM {S}.memory_item WHERE investigation_id = %s ORDER BY item_id", (inv_b,)).fetchall()]
        export_ok = md_ok and db_b == [(i["item_id"], i["kind"], i["text"], i["evidence"], i["status"]) for i in exp["items"]]
        con.close()
    check("M5", "export (JSON, Markdown) = database; recorded sessions replay offline", export_ok and not rep_bad,
          {"export_items": len(exp["items"]), "markdown_has_every_item": md_ok, "replay_mismatch": rep_bad})

    ok = all(c["pass"] for c in checks)
    card = json.loads((ROOT / "config" / "phase5_scorecard.json").read_text(encoding="utf-8"))["items"]
    passed = {c["id"] for c in checks if c["pass"]}
    scorecard = {k: all(x in passed for x in v["criteria"]) for k, v in card.items()}
    if evidence:
        evidence.write_text(json.dumps({"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "all_pass": ok, "checks": checks, "scorecard": scorecard,
                                        "scorecard_score": f"{sum(scorecard.values())}/{len(scorecard)}"},
                                       indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks pass")
    if not offline:
        for k, v in scorecard.items():
            print(f"  {'PASS' if v else 'FAIL'} {k}")
        print(f"Scorecard: {sum(scorecard.values())}/{len(scorecard)}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 5 verifier")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--evidence", type=Path, default=None)
    a = ap.parse_args()
    sys.exit(main(a.offline, a.evidence or (None if a.offline else RES / "verify_phase5.json")))
