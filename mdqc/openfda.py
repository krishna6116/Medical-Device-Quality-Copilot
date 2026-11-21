"""Small, polite client for the openFDA device endpoints.

Why a client of our own instead of calling `requests` everywhere:
- one place for the base URL, the optional API key and the rate limit,
- one place that knows openFDA's paging rules (limit <= 1000, skip <= 25000,
  `search_after` links for anything deeper),
- one place that trims fields that can be huge (a single recall's
  `code_info` lot list was 9.8 MB in the Phase 1 access check).

The API key is optional. Without one openFDA allows 240 requests/minute and
1,000 requests/day per IP address; with a free key, 120,000/day. The key is
read from the environment (`OPENFDA_API_KEY`, set in `.env`), never from code.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

BASE_URL = "https://api.fda.gov"
ENDPOINTS = {
    "event": "/device/event.json",  # MAUDE adverse-event reports (MDRs)
    "recall": "/device/recall.json",  # recall records (one per product/res number)
    "enforcement": "/device/enforcement.json",  # weekly enforcement report entries
    "classification": "/device/classification.json",  # product code -> device name, class
}
MAX_LIMIT_WITH_KEY = 1000
MAX_LIMIT_NO_KEY = 999  # observed 2026-11-21: limit=1000 on /device/event without a key -> 403 API_KEY_MISSING
MAX_SKIP = 25000
RETRY_STATUS = {429, 500, 502, 503, 504}
TRUNCATE_FIELDS ={"code_info": 2000, "more_code_info": 2000}  # characters kept


def build_search(product_code: str | None = None, date_field: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 extra: list[str] | None = None) -> str:
    """Build an openFDA `search` string, e.g.
    device.device_report_product_code:FRN+AND+date_received:[20240101+TO+20241231].

    Terms are joined with '+AND+' (openFDA's syntax; '+' stands for a space).
    Dates are YYYYMMDD.
    """
    terms: list[str] = []
    if product_code:
        terms.append(f"device.device_report_product_code:{product_code}")
    if date_field:
        if not (date_from and date_to):
            raise ValueError("date_field needs both date_from and date_to")
        for d in (date_from, date_to):
            if len(d) != 8 or not d.isdigit():
                raise ValueError(f"dates must be YYYYMMDD, got {d!r}")
        terms.append(f"{date_field}:[{date_from}+TO+{date_to}]")
    terms.extend(extra or [])
    return "+AND+".join(terms)


def truncate_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with oversized free-text fields cut down (marked with '...[truncated]')."""
    out = dict(rec)
    for key, n in TRUNCATE_FIELDS.items():
        val = out.get(key)
        if isinstance(val, str) and len(val) > n:
            out[key] = val[:n] + "...[truncated]"
    return out


def next_search_after(link_header: str | None) -> str | None:
    """Pull the `search_after` token out of an HTTP Link header (rel="next"), if any.

    The token is returned still URL-encoded (e.g. '0%3D10000516'), because we paste it
    straight back into the next URL.
    """
    if not link_header or 'rel="next"' not in link_header:
        return None
    url = link_header.split(";")[0].strip().strip("<>")
    for part in urlparse(url).query.split("&"):
        key, _, value = part.partition("=")
        if key == "search_after" and value:
            return value
    return None


@dataclass
class OpenFDAClient:
    api_key: str | None = field(default_factory=lambda: os.environ.get("OPENFDA_API_KEY") or None)
    min_interval_s: float = 0.3  # ~200 requests/minute, under the 240/minute limit
    timeout_s: float = 120.0
    max_attempts: int = 6  # retries on 429 / 5xx / dropped connections
    session: requests.Session = field(default_factory=requests.Session)
    _last_call: float = 0.0

    @property
    def max_limit(self) -> int:
        return MAX_LIMIT_WITH_KEY if self.api_key else MAX_LIMIT_NO_KEY

    def _url(self, endpoint: str, params: dict[str, Any]) -> str:
        # openFDA wants literal '+', ':' and '[ ]' in `search`, so we build the query by hand
        # instead of letting requests percent-encode it.
        if endpoint not in ENDPOINTS:
            raise ValueError(f"unknown endpoint {endpoint!r}; choose from {sorted(ENDPOINTS)}")
        p = dict(params)
        if self.api_key:
            p["api_key"] = self.api_key
        query = "&".join(f"{k}={v}" for k, v in p.items() if v is not None and v != "")
        return f"{BASE_URL}{ENDPOINTS[endpoint]}" + (f"?{query}" if query else "")

    def get(self, endpoint: str, **params: Any) -> tuple[dict[str, Any], requests.Response]:
        """One request. Returns (json, response). openFDA's 404 'No matches found!' becomes an empty result."""
        limit = params.get("limit")
        if limit is not None and int(limit) > self.max_limit:
            raise ValueError(f"limit {limit} > {self.max_limit} (no API key)" if not self.api_key
                             else f"limit {limit} > {self.max_limit}")
        skip = params.get("skip")
        if skip is not None and int(skip) > MAX_SKIP:
            raise ValueError(f"skip {skip} > {MAX_SKIP}; use search_after paging instead")
        url = self._url(endpoint, params)
        for attempt in range(self.max_attempts):
            wait = self.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=self.timeout_s)
            except (requests.ConnectionError, requests.Timeout):
                resp = None
            self._last_call = time.monotonic()
            if resp is not None and resp.status_code not in RETRY_STATUS:
                break
            if attempt == self.max_attempts - 1:
                if resp is None:
                    raise requests.ConnectionError(f"no response after {self.max_attempts} attempts: {url}")
                break
            time.sleep(min(60.0, 2.0 ** (attempt + 1)))  # 2, 4, 8, 16 s ... backoff
        if resp.status_code == 404:
            return {"meta": {"results": {"total": 0}}, "results": []}, resp
        resp.raise_for_status()
        return resp.json(), resp

    def iter_records(self, endpoint: str, search: str, page_size: int | None = None,
                     max_records: int | None = None) -> Iterator[dict[str, Any]]:
        """Yield every matching record, following search_after links (works past skip=25000)."""
        size = min(page_size or self.max_limit, self.max_limit)
        params: dict[str, Any] = {"search": search, "limit": size}
        n = 0
        while True:
            data, resp = self.get(endpoint, **params)
            for rec in data.get("results", []):
                yield truncate_record(rec)
                n += 1
                if max_records is not None and n >= max_records:
                    return
            token = next_search_after(resp.headers.get("Link"))
            if not token or not data.get("results"):
                return
            params = {"search": search, "limit": size, "skip": 0, "search_after": token}
