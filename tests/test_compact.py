"""Tests for compact dataclass conversion."""
from zammadog.compact import compact_log, compact_span, CompactLog, CompactSpan, MSG_MAX


def _raw_log(**kwargs):
    base = {
        "id": "log-1",
        "attributes": {
            "timestamp": "2026-05-05T12:00:00Z",
            "service": "ms-foo",
            "status": "error",
            "message": "Something went wrong",
            "trace_id": "abc123",
            "error": {"kind": "NullPointerException"},
        },
    }
    base["attributes"].update(kwargs)
    return base


def _raw_span(**kwargs):
    base = {
        "id": "span-1",
        "attributes": {
            "start_timestamp": "2026-05-05T12:00:00Z",
            "service": "ms-foo",
            "resource_name": "GET /health",
            "custom": {"duration": 5_000_000, "error": {"type": "java.lang.RuntimeException"}},
            "status": "0",
            "meta": {"trace_id": "xyz789"},
            "tags": [],
        },
    }
    base["attributes"].update(kwargs)
    return base


def test_compact_log_basic():
    log = compact_log(_raw_log())
    assert log.ts == "2026-05-05T12:00:00Z"
    assert log.svc == "ms-foo"
    assert log.status == "error"
    assert log.msg == "Something went wrong"
    assert log.trace_id == "abc123"
    assert log.error_kind == "NullPointerException"


def test_compact_log_message_truncated():
    long_msg = "x" * 500
    log = compact_log(_raw_log(message=long_msg))
    assert len(log.msg) == MSG_MAX + 1  # +1 for ellipsis char
    assert log.msg.endswith("…")


def test_compact_log_missing_fields():
    log = compact_log({"id": "x", "attributes": {}})
    assert log.svc is None
    assert log.status is None
    assert log.trace_id is None
    assert log.error_kind is None
    assert log.msg == ""


def test_compact_span_basic():
    span = compact_span(_raw_span())
    assert span.svc == "ms-foo"
    assert span.resource == "GET /health"
    assert span.duration_ms == 5
    assert span.trace_id == "xyz789"
    assert span.error_type == "java.lang.RuntimeException"


def test_compact_span_missing():
    span = compact_span({"id": "x", "attributes": {}})
    assert span.svc is None
    assert span.duration_ms is None
    assert span.trace_id is None
    assert span.error_type is None
