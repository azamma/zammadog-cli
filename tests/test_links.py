"""Tests for URL parser."""
import pytest
from zammadog.links import extract_datadog_links, DatadogLink


def test_logs_url_with_query():
    text = "Check https://app.datadoghq.com/logs?query=service%3Ams-foo+status%3Aerror&from_ts=1234&to_ts=5678"
    links = extract_datadog_links(text)
    assert len(links) == 1
    link = links[0]
    assert link.kind == "logs"
    assert link.site == "datadoghq.com"
    assert link.query == "service:ms-foo status:error"
    assert link.from_ts == "1234"
    assert link.to_ts == "5678"


def test_apm_trace_url():
    text = "See https://app.datadoghq.com/apm/trace/abc123def456"
    links = extract_datadog_links(text)
    assert len(links) == 1
    link = links[0]
    assert link.kind == "apm-trace"
    assert link.trace_id == "abc123def456"


def test_apm_trace_via_query_param():
    text = "https://app.datadoghq.com/apm/home?traceId=xyz789"
    links = extract_datadog_links(text)
    assert links[0].kind == "apm-trace"
    assert links[0].trace_id == "xyz789"


def test_apm_watchdog_url_skipped():
    text = "https://app.datadoghq.com/apm/home?view=services&recommendationId=abc"
    links = extract_datadog_links(text)
    assert links[0].kind == "apm-services"


def test_eu_site():
    text = "https://app.datadoghq.eu/logs?query=service%3Afoo"
    links = extract_datadog_links(text)
    assert links[0].site == "datadoghq.eu"


def test_apm_search_with_trace_query():
    text = "https://app.datadoghq.com/apm/home?traceQuery=service%3Afoo"
    links = extract_datadog_links(text)
    assert links[0].kind == "apm-search"
    assert links[0].query == "service:foo"


def test_missing_params():
    text = "https://app.datadoghq.com/logs"
    links = extract_datadog_links(text)
    assert links[0].query is None
    assert links[0].from_ts is None


def test_no_dd_urls():
    assert extract_datadog_links("no urls here") == []


def test_malformed_ignored():
    assert extract_datadog_links("https://notdatadog.com/logs?q=x") == []


def test_dedup():
    url = "https://app.datadoghq.com/logs?query=foo"
    links = extract_datadog_links(f"{url} and again {url}")
    assert len(links) == 1


def test_trailing_punctuation_stripped():
    text = "See https://app.datadoghq.com/logs?query=foo."
    links = extract_datadog_links(text)
    assert not links[0].raw_url.endswith(".")
