"""Phase 8 app tests (Streamlit AppTest). Run in the app's own environment: pip install -r app/requirements.txt pytest; pytest tests/app
Skipped in the project environment (no streamlit there). Expected values are recomputed here with csv/json only (no pandas, no app code)."""

import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "dashboards" / "snapshots"
APP = ROOT / "app" / "streamlit_app.py"
PAGES = ["home", "investigation", "how", "ask", "trends", "companies", "drift", "memory", "evaluation", "about"]
# sentence fragments each page must show (from the pre-registered scorecard, A2.2 and A2.3)
REQUIRED = {"home": ["recorded answers, replayed", "scored 4/5"], "investigation": ["cannot show that the recall caused", "recorded answers, replayed", "not failure rates", "still arriving"],
            "how": ["scored 4/5", "came from an AI, not a person"], "ask": ["recorded answers, replayed", "Accuracy was measured on 2022-2024"],
            "trends": ["still arriving", "not failure rates"], "companies": ["not failure rates"], "drift": ["still arriving", "could not detect"],
            "memory": ["only in this browser session"], "evaluation": ["scored 4/5", "came from an AI, not a person", "Accuracy was measured on 2022-2024"],
            "about": ["not failure rates", "still arriving", "scored 4/5", "came from an AI, not a person", "Not medical advice"]}


def rows(name):
    with (SNAP / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def js(name):
    return json.loads((SNAP / name).read_text(encoding="utf-8"))


def page(name, app=APP):
    at = AppTest.from_file(str(app), default_timeout=60)
    at.run()
    at.switch_page(f"views/{name}.py").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def text(at) -> str:
    parts = [x.value for kind in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "success", "error") for x in getattr(at, kind)]
    return " ".join(str(p) for p in parts) + " " + html_text(at)


def html_text(at) -> str:
    """Visible text of the st.html blocks (cards, hero, steps), tags removed."""
    import html as h
    import re
    return " ".join(h.unescape(re.sub(r"<style.*?</style>|<[^>]+>", " ", x.proto.body, flags=re.S)) for x in at.get("html"))


def cards(at) -> dict:
    """label -> value of every card on the page."""
    import html as h
    import re
    out = {}
    for x in at.get("html"):
        for k, v in re.findall(r'<div class="k">(.*?)</div><div class="v">(.*?)</div>', x.proto.body):
            out[h.unescape(k)] = h.unescape(v)
    return out


def metrics(at) -> dict:
    return {m.label: m.value for m in at.metric}


def missing(at, name):
    t = text(at)
    return [s for s in REQUIRED[name] if s not in t]


@pytest.mark.parametrize("name", PAGES)
def test_page_renders_with_required_sentences(name):
    at = page(name)
    assert not missing(at, name)
    assert "Not medical advice" in text(at)


def battery():
    b = {}
    for r in rows("battery.csv"):
        b[(r["quarter"], r["company"])] = int(r["reports"])
    fam = {}
    for r in rows("battery_brands.csv"):
        named = r["family"] in ("ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA")
        n, t = fam.get(r["period"], (0, 0))
        fam[r["period"]] = (n + int(r["reports"]) * named, t + int(r["reports"]))
    return b, fam


def test_home_numbers():
    at = page("home")
    c, R, b = cards(at), js("results.json"), battery()[0]
    assert c["FDA reports"] == f"{sum(int(r['reports']) for r in rows('quarterly.csv')):,}" == "233,264"
    assert c["Accuracy"] == f"{R['phase6']['haiku_correct']}/{R['phase6']['haiku_of']}" == "78/80"
    assert c["Data checks"] == R["phase7c"]["checks"] == "9/9"
    q3, q4 = b[("2025Q3", "BOSTON SCIENTIFIC")], b[("2025Q4", "BOSTON SCIENTIFIC")]
    assert (q3, q4) == (325, 1904) and c["Drift alert"] == f"{q4 / q3:.1f}×" == "5.9×"
    t = html_text(at)
    assert f"{len(rows('recalls.csv')):,} recalls" in t and f"${R['phase6']['haiku_cost_usd']:.2f} in total" in t and f"{q3:,} to {q4:,}" in t
    assert f"scored {R['phase6']['opus_correct']}/80 for ${R['phase6']['opus_cost_usd']:.2f}" in t


def test_investigation_numbers():
    at = page("investigation")
    c, (b, fam), t = cards(at), battery(), text(at)
    assert c["Boston Scientific, 2025Q3"] == "325" and c["Boston Scientific, 2025Q4"] == "1,904"
    assert c["Abbott, same quarters"] == f"{b[('2025Q3', 'ABBOTT')]:,} → {b[('2025Q4', 'ABBOTT')]:,}"
    (a1, t1), (a2, t2) = fam["2025Q1-2025Q3"], fam["2025Q4-2026Q3"]
    assert (a2, t2) == (9497, 9736) and f"**{100 * a2 / t2:.1f}%**" in t and f"({a2:,} of {t2:,})" in t and f"{100 * a1 / t1:.1f}% ({a1:,} of {t1:,})" in t
    rec = [r for r in rows("recalls.csv") if r["product"] == "LWP" and r["company"] == "BOSTON SCIENTIFIC" and r["started"] == "2025-08-20"]
    first = min(rec, key=lambda r: r["recall_number"])
    assert f"Recall {first['recall_number']} and {len(rec) - 1} related records (event {first['recall_event']}, started 2025-08-20)" in t
    assert "high battery impedance" in first["reason"]


def test_drift_numbers():
    d = rows("drift.csv")
    m = metrics(page("drift"))
    assert m["Checks"] == str(3 * len(d)) and m["Flags"] == str(sum(len(r["flags"].split(";")) for r in d if r["flags"])) == "5"
    assert m["Quarters flagged"] == str(sum(1 for r in d if r["flags"])) == "4"


def test_evaluation_numbers():
    m, R = metrics(page("evaluation")), js("results.json")
    assert m["Claude Haiku 5.5"] == "78/80" and m["Claude Opus 5.5"] == "76/80"
    assert m["Opus minus Haiku (95% interval)"] == f"{100 * R['phase6']['difference']:+.1f} points" == "-2.5 points"
    assert m["Planted unsafe sentences caught"] == R["phase7b"]["caught"] == "38/40"
    assert m["Questions answered correctly"] == R["phase7c"]["correct"] == "20/20"


@pytest.mark.parametrize("code", ["LPH", "JWH", "MBH", "LWP", "LZG"])
def test_trends_and_companies_every_product(code):
    at = page("trends")
    at.selectbox[0].set_value(code).run()
    assert not at.exception
    want = sum(int(r["reports"]) for r in rows("quarterly_modes.csv") if r["product"] == code and r["quarter"].startswith("2025"))
    assert f"Failure modes in 2025 ({want:,} reports)" in text(at)
    at = page("companies")
    at.selectbox[0].set_value(code).run()
    assert not at.exception
    rc = [r for r in rows("recalls.csv") if r["product"] == code]
    assert f"Recalls: {len(rc):,} records in {len({r['recall_event'] for r in rc}):,} recall events (all years)" in text(at)
    total = sum(int(r["reports"]) for r in rows("makers.csv") if r["product"] == code)
    assert f"{total:,} reports in total." in text(at)
    top = Counter()
    for r in rows("makers.csv"):
        if r["product"] == code:
            top[r["company"]] += int(r["reports"])
    first = min(top.items(), key=lambda kv: (-kv[1], kv[0]))
    df = at.dataframe[0].value
    assert (df.iloc[0]["company"], int(df.iloc[0]["reports"])) == first


def test_every_recorded_answer():
    A = js("answers.json")
    at = page("ask")
    seen = 0
    for s in sorted({a["set"] for a in A}):
        at.radio[0].set_value(s).run()
        for a in [x for x in A if x["set"] == s]:
            at.selectbox[1].set_value(a["id"]).run()
            assert not at.exception
            m = metrics(at)
            assert m["Cost of this answer"] == f"${a['cost_usd']:.4f}" and m["Model calls"] == str(a["steps"]) and m["Model"] == a["model"]
            assert m["Graded"] == ("not graded" if not a["graded"] else "correct" if a["correct"] else "wrong")
            seen += 1
    assert seen == len(A) == 105


def test_memory_sandbox_refuses_personal_data_and_deletes():
    at = page("memory")
    n0 = len(at.session_state["memory"])
    at.text_input[0].set_value("Call the surgeon on 555-201-3344")
    at.button[0].click().run()  # inside a form, typing is sent with the click
    assert any("personal data" in e.value for e in at.error) and len(at.session_state["memory"]) == n0
    at.text_input[0].set_value("Check whether lot 4411 appears in other reports")
    at.button[0].click().run()
    assert len(at.session_state["memory"]) == n0 + 1 and any("Saved" in s.value for s in at.success)
    first = at.session_state["memory"][0]["id"]
    next(b for b in at.button if b.key == f"del{first}").click().run()
    assert first not in [m["id"] for m in at.session_state["memory"]]
    at.text_input[0].set_value("ok")
    at.button[0].click().run()
    assert any("5 to 500 characters" in e.value for e in at.error)


def test_about_shows_the_data_checksum():
    assert js("manifest.json")["data_checksum"] in text(page("about"))


# ---- planted page bugs: the checks above must be able to fail ------------------------------------------------------------
def planted_app(tmp_path, view, change):
    app = tmp_path / "app"
    shutil.copytree(ROOT / "app", app)
    shutil.copytree(ROOT / "dashboards", tmp_path / "dashboards")
    p = app / "views" / f"{view}.py"
    p.write_text(change(p.read_text(encoding="utf-8")), encoding="utf-8")
    return app / "streamlit_app.py"


def test_planted_missing_warning_is_caught(tmp_path):
    app = planted_app(tmp_path, "trends", lambda t: t.replace("st.caption(C.INCOMPLETE.format(q=last))", "pass"))
    at = AppTest.from_file(str(app), default_timeout=60)
    at.run()
    at.switch_page("views/trends.py").run()
    assert missing(at, "trends") == ["still arriving"]


def test_planted_page_error_is_caught(tmp_path):
    app = planted_app(tmp_path, "drift", lambda t: t.replace('C.csv("drift.csv")', 'C.csv("no_such_file.csv")'))
    at = AppTest.from_file(str(app), default_timeout=60)
    at.run()
    at.switch_page("views/drift.py").run()
    assert at.exception
