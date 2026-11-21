"""Offline tests for the openFDA client (no network: CI must not depend on FDA being up)."""

import pytest

from mdqc.openfda import (MAX_LIMIT_NO_KEY, OpenFDAClient, build_search, next_search_after,
                          truncate_record)


def test_build_search_product_and_dates():
    s = build_search(product_code="FRN", date_field="date_received", date_from="20240101", date_to="20241231")
    assert s == "device.device_report_product_code:FRN+AND+date_received:[20240101+TO+20241231]"


def test_build_search_rejects_bad_dates():
    with pytest.raises(ValueError):
        build_search(date_field="date_received", date_from="2024-01-01", date_to="20241231")
    with pytest.raises(ValueError):
        build_search(date_field="date_received", date_from="20240101")


def test_truncate_record_cuts_only_long_fields():
    rec = {"code_info": "x" * 5000, "reason_for_recall": "y" * 5000}
    out = truncate_record(rec)
    assert out["code_info"].endswith("...[truncated]") and len(out["code_info"]) < 2100
    assert out["reason_for_recall"] == rec["reason_for_recall"]
    assert rec["code_info"] == "x" * 5000  # original untouched


def test_next_search_after_keeps_token_encoded():
    link = '<https://api.fda.gov/device/event.json?limit=5&skip=0&search_after=0%3D10000516>; rel="next"'
    assert next_search_after(link) == "0%3D10000516"
    assert next_search_after(None) is None
    assert next_search_after('<https://x?y=1>; rel="prev"') is None


def test_client_limits_without_key():
    c = OpenFDAClient(api_key=None)
    assert c.max_limit == MAX_LIMIT_NO_KEY == 999
    with pytest.raises(ValueError):
        c.get("event", limit=1000)
    with pytest.raises(ValueError):
        c.get("event", limit=1, skip=25001)
    with pytest.raises(ValueError):
        c.get("nope", limit=1)


def test_url_adds_key_and_keeps_search_literal():
    c = OpenFDAClient(api_key="TESTKEY")
    url = c._url("event", {"search": "a:[1+TO+2]", "limit": 5})
    assert url == "https://api.fda.gov/device/event.json?search=a:[1+TO+2]&limit=5&api_key=TESTKEY"
