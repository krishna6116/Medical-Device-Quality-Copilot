"""Phase 7c: scope switch, loader options and the question grader on planted answers. No database, no API."""

import pytest

from mdqc import eval7c as e
from mdqc import tools as t
from mdqc.assistant import SYSTEM, SYSTEM_ALL


def test_scope_all_is_opt_in():
    assert t._window() == ("2022-01-01", "2024-12-31") and t._date("2026-05-01", "2022-01-01") == "2024-12-31"
    token = t._SCOPE.set("all")
    try:
        assert t._date("2026-05-01", "2022-01-01") == "2026-05-01"
    finally:
        t._SCOPE.reset(token)
    assert "offset" not in t.SCHEMAS["find_recalls"]["properties"] and "offset" in t.SCHEMAS_ALL["find_recalls"]["properties"]
    assert "mid-November 2026" in SYSTEM_ALL and "mid-November" not in SYSTEM


def test_scoped_connection_rewrites_only_schema_names():
    class C:
        def execute(self, sql, params=None):
            return sql
    s = t.ScopedCon(C()).execute("SELECT x FROM core.fact_report JOIN analytics.signal_month WHERE score.x = 1 AND y = 'core'")
    assert s == "SELECT x FROM core_all.fact_report JOIN analytics_all.signal_month WHERE score.x = 1 AND y = 'core'"


def test_offset_limits():
    assert t._offset(None) == 0 and t._offset(100) == 100
    for bad in (-1, 101, "x"):
        with pytest.raises(t.ToolError):
            t._offset(bad)


@pytest.mark.parametrize("check,answer,ok", [
    ({"type": "contains", "value": "Z-0026-2022"}, "It is Z-0026-2022.", True), ({"type": "contains", "value": "Z-0026-2022"}, "It is Z-0026-20221.", False),
    ({"type": "contains", "value": "887550"}, "LOT 887,550", True), ({"type": "contains", "value": "887550"}, "1887550", False),
    ({"type": "scope"}, "2020 isn't available; the data starts in 2022.", True), ({"type": "scope"}, "There were 512 reports in 2020.", False),
    ({"type": "number", "value": 12075}, "There were 12,075 reports.", True), ({"type": "number", "value": 12075}, "There were 12,076 reports.", False)])
def test_grader(check, answer, ok):
    assert e.check({"check": check}, {"answer": answer, "stop": "answered"})[0] is ok
    assert not e.check({"check": check}, {"answer": answer, "stop": "budget"})[0]


def test_twenty_questions():
    q = e.questions()
    assert len(q) == 20 and sum(x["category"] in ("paging", "narrative") for x in q) == 4 and sum(x["category"] == "scope" for x in q) == 2
