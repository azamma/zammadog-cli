"""Tests for render_endpoint_report_html."""
from __future__ import annotations
import json
from html.parser import HTMLParser

import pytest

from zammadog.compact import CompactSpan
from zammadog.render import render_endpoint_report_html


SPANS = [
    CompactSpan(ts="2026-05-05T12:00:00Z", svc="my-svc", op="http.request",
                resource="POST /my-svc/v1/foo", duration_ms=120, status="0",
                trace_id="abc123", error_type=None),
    # N+1: SELECT appears 3 times in trace abc123
    CompactSpan(ts="2026-05-05T12:00:01Z", svc="my-svc", op="db.query",
                resource="SELECT * FROM items", duration_ms=45, status="0",
                trace_id="abc123", error_type=None),
    CompactSpan(ts="2026-05-05T12:00:01Z", svc="my-svc", op="db.query",
                resource="SELECT * FROM items", duration_ms=48, status="0",
                trace_id="abc123", error_type=None),
    CompactSpan(ts="2026-05-05T12:00:01Z", svc="my-svc", op="db.query",
                resource="SELECT * FROM items", duration_ms=52, status="0",
                trace_id="abc123", error_type=None),
    CompactSpan(ts="2026-05-05T12:00:02Z", svc="redis", op="redis.get",
                resource="GET session", duration_ms=3, status="0",
                trace_id="abc123", error_type=None),
    CompactSpan(ts="2026-05-05T12:00:03Z", svc="my-svc", op="db.query",
                resource="SELECT * FROM items", duration_ms=51, status="0",
                trace_id="def456", error_type=None),
    CompactSpan(ts="2026-05-05T12:00:04Z", svc="my-svc", op="http.request",
                resource="POST /my-svc/v1/foo", duration_ms=200, status="error",
                trace_id="def456", error_type="RuntimeError"),
]
N_TRACES = 2
ENDPOINT = "POST /my-svc/v1/foo"
SERVICE = "my-svc"


def _render() -> str:
    return render_endpoint_report_html(
        SPANS, N_TRACES, ENDPOINT, SERVICE, "now-1h", "now"
    )


class _Validator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors: list[str] = []

    def handle_error(self, message):
        self.errors.append(message)


def test_starts_with_doctype():
    out = _render()
    assert out.strip().lower().startswith("<!doctype html")


def test_contains_endpoint():
    out = _render()
    assert ENDPOINT in out


def test_contains_service_badge():
    out = _render()
    assert SERVICE in out


def test_json_embed_parseable():
    out = _render()
    start = out.index('id="agg-data">') + len('id="agg-data">')
    end = out.index("</script>", start)
    data = json.loads(out[start:end])
    assert isinstance(data, list)
    assert len(data) > 0
    assert "svc" in data[0]
    assert "avg" in data[0]


def test_raw_json_embed_parseable():
    out = _render()
    start = out.index('id="raw-data">') + len('id="raw-data">')
    end = out.index("</script>", start)
    data = json.loads(out[start:end])
    assert len(data) == len(SPANS)  # updated if SPANS changes
    assert data[0]["trace_id"] == "abc123"


def test_trace_id_links_in_raw_json():
    out = _render()
    assert "app.datadoghq.com/apm/trace/" in out


def test_html_parses_without_error():
    validator = _Validator()
    validator.feed(_render())
    assert validator.errors == []


def test_empty_spans_valid_html():
    out = render_endpoint_report_html([], 0, "GET /empty", None, "now-1h", "now")
    assert "<!doctype html" in out.lower()
    assert "GET /empty" in out
    validator = _Validator()
    validator.feed(out)
    assert validator.errors == []


def test_xss_escape():
    evil = "<script>alert(1)</script>"
    out = render_endpoint_report_html(
        [CompactSpan(ts="t", svc=evil, op="x", resource="x",
                     duration_ms=1, status="0", trace_id="t1", error_type=None)],
        1, evil, evil, "now-1h", "now"
    )
    assert "<script>alert(1)</script>" not in out.replace(
        '<script type="application/json"', ""
    ).replace("<script>", "").replace("</script>", "")


def test_n_plus_one_detection():
    out = _render()
    start = out.index('id="agg-data">') + len('id="agg-data">')
    end = out.index("</script>", start)
    data = json.loads(out[start:end])
    # SELECT * FROM items appears in both traces → cpt > 1
    db_rows = [r for r in data if "SELECT" in r["resource"]]
    assert any(r["cpt"] > 1 for r in db_rows)


def test_from_url_in_output():
    out = _render()
    assert "now-1h" in out
    assert "now" in out
