"""Tests for the parser-driven report framework (--report path)."""
from __future__ import annotations
import json
from html.parser import HTMLParser
from unittest.mock import patch, MagicMock

import pytest

from zammadog.cli import main
from zammadog.compact import CompactLog
from zammadog.report import (
    Chart, KPI, ReportingParser, ReportModel, TableSection, build_generic_report,
)
from zammadog.render import render_report_html
from zammadog.parsers.global66_parser import Global66Parser


# ── report.py dataclasses & build_generic_report ────────────────────────────


def _log(msg: str, status: str = "INFO", svc: str = "my-svc",
         ts: str = "2026-06-03T12:00:00Z") -> CompactLog:
    return CompactLog(ts=ts, svc=svc, status=status, msg=msg, trace_id="t1", error_kind=None)


def test_build_generic_report_empty():
    m = build_generic_report([])
    assert m.title == "(no results)"
    assert m.kpis == [KPI("Total", "0")]
    assert m.charts == []
    assert m.sections == []


def test_build_generic_report_clusters_mask_digits():
    rows = [
        _log("user 42 logged in"),
        _log("user 99 logged in"),
        _log("user 17 logged in"),
        _log("Failed: error code 500"),
    ]
    m = build_generic_report(rows)
    assert len(m.charts) == 1
    sig_counts = m.charts[0].bars
    # "user # logged in" cluster → count 3
    by_sig = {label: count for label, count in sig_counts}
    user_cluster = next(label for label in by_sig if "user" in label and "logged in" in label)
    assert by_sig[user_cluster] == 3


def test_build_generic_report_kpi_tone_for_errors():
    rows = [_log("boom", status="ERROR"), _log("ok", status="INFO")]
    m = build_generic_report(rows)
    err_kpi = next(k for k in m.kpis if k.label == "Errors")
    assert err_kpi.value == "1"
    assert err_kpi.tone == "red"


def test_reporting_parser_isinstance_duck_typed():
    class P:
        def report(self, rows): return build_generic_report(rows)
    assert isinstance(P(), ReportingParser)

    class Q:
        pass
    assert not isinstance(Q(), ReportingParser)


# ── render_report_html ──────────────────────────────────────────────────────


class _Validator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors: list[str] = []

    def handle_error(self, message):
        self.errors.append(message)


def _basic_model() -> ReportModel:
    return ReportModel(
        title="Test report",
        kpis=[KPI("Total", "42"), KPI("Errors", "3", "red")],
        charts=[Chart("Top clusters", [("A", 10.0), ("B", 5.0)])],
        sections=[TableSection(title="rows", columns=["A", "B"], rows=[[1, "foo"], [2, "bar"]])],
    )


def test_render_report_html_doctype():
    out = render_report_html(
        _basic_model(), source="grp", time_range=("now-1h", "now"),
        generated_at="2026-06-03T12:00:00Z", version="0.1.0",
    )
    assert out.strip().lower().startswith("<!doctype html")


def test_render_report_html_parses():
    out = render_report_html(
        _basic_model(), source="grp", time_range=("now-1h", "now"),
        generated_at="2026-06-03T12:00:00Z", version="0.1.0",
    )
    v = _Validator()
    v.feed(out)
    assert v.errors == []


def test_render_report_html_embeds_sections_and_charts():
    out = render_report_html(
        _basic_model(), source="grp", time_range=("now-1h", "now"),
        generated_at="2026-06-03T12:00:00Z", version="0.1.0",
    )
    start = out.index('id="r-sections-data">') + len('id="r-sections-data">')
    end = out.index("</script>", start)
    sections = json.loads(out[start:end])
    assert isinstance(sections, list) and len(sections) == 1
    assert sections[0]["columns"] == ["A", "B"]
    assert sections[0]["rows"] == [[1, "foo"], [2, "bar"]]

    start = out.index('id="r-charts-data">') + len('id="r-charts-data">')
    end = out.index("</script>", start)
    charts = json.loads(out[start:end])
    assert charts[0]["title"] == "Top clusters"
    assert charts[0]["bars"] == [["A", 10.0], ["B", 5.0]]


def test_render_report_html_empty_model_valid():
    m = ReportModel(title="(no results)", kpis=[KPI("Total", "0")], charts=[], sections=[])
    out = render_report_html(
        m, source="", time_range=("now-1h", "now"),
        generated_at="2026-06-03T12:00:00Z", version="0.1.0",
    )
    assert "<!doctype html" in out.lower()
    v = _Validator()
    v.feed(out)
    assert v.errors == []


def test_render_report_html_xss_in_section_cells():
    evil = "</script><img src=x onerror=alert(1)>"
    m = ReportModel(
        title="t", kpis=[], charts=[],
        sections=[TableSection(title="s", columns=["MSG"], rows=[[evil]])],
    )
    out = render_report_html(
        m, source="", time_range=("now-1h", "now"),
        generated_at="2026-06-03T12:00:00Z", version="0.1.0",
    )
    # Safety criteria:
    # 1. The raw "</script>" must not appear unescaped outside <script> blocks.
    # 2. Inside <script type="application/json"> blocks, the breakout is
    #    backslash-escaped (safe), and the JSON parses back to the original evil.
    import re
    raw_breakout = "</script><img"
    blocks = re.findall(r"<script[^>]*>.*?</script>", out, re.DOTALL)
    outside = re.sub(r"<script[^>]*>.*?</script>", "", out, flags=re.DOTALL)
    assert raw_breakout not in outside
    json_blob = next(b for b in blocks if 'id="r-sections-data"' in b)
    # Raw breakout absent; backslash-escaped form present.
    assert raw_breakout not in json_blob
    assert "<\\/script>" in json_blob
    # And the JSON still round-trips to the original evil string.
    body = json_blob.split(">", 1)[1].rsplit("</script>", 1)[0]
    parsed = json.loads(body)
    assert parsed[0]["rows"][0][0] == evil


# ── global66_parser.report() real-shape fixture ─────────────────────────────


def _g66_log(msg: str, status: str = "INFO", svc: str = "customer-PROD-MS") -> CompactLog:
    return CompactLog(ts="2026-06-03T00:00:00.000Z", svc=svc, status=status,
                      msg=msg, trace_id="t1", error_kind=None)


def test_global66_report_extracts_error_code_and_reason():
    rows = [
        _g66_log('ErrorResponse : {"code":"000602","reason":"REQUEST_PARAMETER_MISSING"}', "ERROR"),
        _g66_log('ErrorResponse : {"code":"000602","reason":"REQUEST_PARAMETER_MISSING"}', "ERROR"),
        _g66_log('ErrorResponse : {"code":"000700","reason":"RATE_LIMIT"}', "ERROR"),
    ]
    p = Global66Parser()
    cleaned = p.parse(rows)
    m = p.report(cleaned)
    err_kpi = next(k for k in m.kpis if k.label == "Errors")
    assert err_kpi.value == "3"
    distinct_kpi = next(k for k in m.kpis if k.label == "Distinct error codes")
    assert distinct_kpi.value == "2"
    sec = next(s for s in m.sections if "Error code" in s.title)
    counts = {r[1]: r[0] for r in sec.rows}
    assert counts["000602 · REQUEST_PARAMETER_MISSING"] == 2
    assert counts["000700 · RATE_LIMIT"] == 1


def test_global66_report_extracts_failing_endpoint_with_status():
    rows = [
        _g66_log("Failed GET request uri=/geolocation/iuse/geocode/basic-location-info, status=400", "ERROR"),
        _g66_log("Failed GET request uri=/mfa/iuse/x, status=500", "ERROR"),
    ]
    m = Global66Parser().report(Global66Parser().parse(rows))
    sec = next(s for s in m.sections if "Endpoint" in s.title)
    by_label = {r[1]: r[0] for r in sec.rows}
    assert by_label["/geolocation/iuse/geocode/basic-location-info  (400)"] == 1
    assert by_label["/mfa/iuse/x  (500)"] == 1


def test_global66_report_groups_warn_device_permission_by_user():
    rows = [
        _g66_log("No device permission found for user fingerprint=abc123", "WARN"),
        _g66_log("No device permission found for user fingerprint=abc123", "WARN"),
        _g66_log("No device permission found for user fingerprint=zzz999", "WARN"),
    ]
    m = Global66Parser().report(Global66Parser().parse(rows))
    sec = next(s for s in m.sections if "device permission" in s.title)
    by_user = {r[1]: r[0] for r in sec.rows}
    assert by_user["fingerprint=abc123"] == 2
    assert by_user["fingerprint=zzz999"] == 1


# ── CLI wiring ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_clients():
    import zammadog.cli as _cli
    _cli._CLIENT = None
    _cli._CW_CLIENT = None
    yield


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_filter_report_html_to_file(mock_boto3_client, tmp_path):
    logs_mock = MagicMock()
    logs_mock.filter_log_events.return_value = {
        "events": [
            {
                "timestamp": 1714908000000,
                "message": "user 42 logged in",
                "logStreamName": "my-stream",
            }
        ]
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    out = tmp_path / "r.html"
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-filter", "-g", "/aws/lambda/foo",
            "--report", "example", "--out", str(out),
        ])
    assert exc.value.code == 0
    body = out.read_text()
    assert "<!doctype html" in body.lower()
    assert "Example report" in body


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_filter_report_with_parser_conflict(mock_boto3_client, capsys):
    mock_boto3_client.side_effect = lambda svc, **kw: MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-filter", "-g", "/aws/lambda/foo",
            "--report", "example", "--parser", "example",
        ])
    assert exc.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_filter_report_unknown_parser_exits_2(mock_boto3_client, capsys):
    mock_boto3_client.side_effect = lambda svc, **kw: MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-filter", "-g", "/aws/lambda/foo",
            "--report", "nope-not-a-parser",
        ])
    assert exc.value.code == 2
    assert "unknown parser" in capsys.readouterr().err


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_search_report_rejects_stats_query(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [{"field": "level", "value": "error"}, {"field": "count(*)", "value": "42"}],
        ],
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-search",
            "-q", "stats count(*) by level",
            "-g", "/aws/lambda/foo",
            "--report", "example",
        ])
    assert exc.value.code == 2
    assert "stats" in capsys.readouterr().err


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_filter_report_json(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.filter_log_events.return_value = {
        "events": [
            {"timestamp": 1714908000000, "message": "user 42 logged in",
             "logStreamName": "my-stream"},
        ]
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-filter", "-g", "/aws/lambda/foo",
            "--report", "example", "--json",
        ])
    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["title"] == "Example report — 1 lines"
    assert data["source"] == "log-group: /aws/lambda/foo"
    assert data["from_ts"] == "now-1h"
    assert data["to_ts"] == "now"
