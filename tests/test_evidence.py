"""Tests for gather_evidence routing and output format."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest

from zammadog.compact import AggregateRow, CompactLog, CompactSpan
from zammadog.evidence import gather_evidence
from zammadog.links import DatadogLink


def _link(kind, query=None, trace_id=None, from_ts=None, to_ts=None):
    return DatadogLink(
        kind=kind,
        site="datadoghq.com",
        query=query,
        from_ts=from_ts,
        to_ts=to_ts,
        env=None,
        service=None,
        trace_id=trace_id,
        raw_url="https://app.datadoghq.com/test",
    )


def _stub_client(logs=None, agg=None, spans=None):
    client = MagicMock()
    client.logs_search.return_value = logs or []
    client.logs_aggregate.return_value = agg or []
    client.apm_search.return_value = spans or []
    client.apm_aggregate.return_value = agg or []
    return client


LOG_ROW = CompactLog(
    ts="2026-05-05T12:00:00Z", svc="ms-foo", status="error",
    msg="boom", trace_id="t1", error_kind=None
)
SPAN_ROW = CompactSpan(
    ts="2026-05-05T12:00:00Z", svc="ms-foo", op="http.get", resource="GET /",
    duration_ms=5, status="0", trace_id="t1", error_type=None
)
AGG_ROW = AggregateRow(groups={"service": "ms-foo", "status": "error"}, value=42)


def test_logs_kind_routes_correctly():
    client = _stub_client(logs=[LOG_ROW], agg=[AGG_ROW])
    result = gather_evidence(client, _link("logs", query="service:ms-foo"), link_num=1)
    assert "# Datadog evidence — link 1 (logs)" in result
    assert "Aggregate" in result
    assert "Sample" in result
    client.logs_aggregate.assert_called_once()
    client.logs_search.assert_called_once()


def test_apm_search_kind_routes():
    client = _stub_client(spans=[SPAN_ROW], agg=[AGG_ROW])
    result = gather_evidence(client, _link("apm-search", query="service:ms-foo"))
    assert "apm-search" in result
    assert "Aggregate" in result
    client.apm_aggregate.assert_called_once()
    client.apm_search.assert_called_once()


def test_apm_trace_kind_routes():
    client = _stub_client(spans=[SPAN_ROW])
    result = gather_evidence(client, _link("apm-trace", trace_id="abc123"))
    assert "abc123" in result
    client.apm_search.assert_called_once()
    # aggregate NOT called for trace
    client.apm_aggregate.assert_not_called()


def test_apm_services_skipped():
    client = _stub_client()
    result = gather_evidence(client, _link("apm-services"))
    assert "skipped" in result
    client.logs_search.assert_not_called()
    client.apm_search.assert_not_called()


def test_unknown_skipped():
    client = _stub_client()
    result = gather_evidence(client, _link("unknown"))
    assert "skipped" in result


def test_apm_trace_no_trace_id():
    client = _stub_client()
    result = gather_evidence(client, _link("apm-trace", trace_id=None))
    assert "No trace_id" in result
    client.apm_search.assert_not_called()


def test_output_format_contains_url():
    client = _stub_client(logs=[LOG_ROW], agg=[AGG_ROW])
    result = gather_evidence(client, _link("logs", query="*"), link_num=2)
    assert "link 2" in result
    assert "datadoghq.com" in result
