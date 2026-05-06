"""Tests for DatadogClient — mocks urllib.request.urlopen."""
from __future__ import annotations
import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from zammadog.client import DatadogClient, DatadogError, MAX_LIMIT


def _make_response(data: dict) -> MagicMock:
    body = json.dumps(data).encode()
    m = MagicMock()
    m.read.return_value = body
    m.__enter__ = lambda s: s
    m.__exit__ = MagicMock(return_value=False)
    return m


def _make_http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.com", code=code, msg="err",
        hdrs=None, fp=BytesIO(body.encode()),
    )


LOGS_RESP = {
    "data": [
        {
            "id": "log1",
            "attributes": {
                "timestamp": "2026-05-05T12:00:00Z",
                "service": "ms-foo",
                "status": "error",
                "message": "boom",
                "trace_id": "t1",
            },
        }
    ]
}

AGG_RESP = {
    "data": {
        "buckets": [
            {"by": {"service": "ms-foo", "status": "error"}, "computes": {"c0": 42}}
        ]
    }
}


@patch("urllib.request.urlopen")
def test_logs_search_returns_compact(mock_open):
    mock_open.return_value = _make_response(LOGS_RESP)
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    rows = client.logs_search("service:ms-foo", "now-1h", "now", limit=5)
    assert len(rows) == 1
    assert rows[0].svc == "ms-foo"


@patch("urllib.request.urlopen")
def test_limit_clamped(mock_open):
    mock_open.return_value = _make_response(LOGS_RESP)
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    # Should not raise; limit gets clamped internally
    client.logs_search("*", "now-1h", "now", limit=999)
    call_payload = json.loads(mock_open.call_args[0][0].data)
    assert call_payload["page"]["limit"] == MAX_LIMIT


def test_window_cap_rejected():
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    with pytest.raises(DatadogError, match="exceeds max"):
        client.logs_search("*", "now-25h", "now")


@patch("urllib.request.urlopen")
def test_5xx_retry(mock_open):
    err = _make_http_error(503)
    mock_open.side_effect = [err, _make_response(LOGS_RESP)]
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    # Second attempt should succeed
    with patch("time.sleep"):
        rows = client.logs_search("*", "now-1h", "now")
    assert len(rows) == 1


@patch("urllib.request.urlopen")
def test_5xx_exhausted_raises(mock_open):
    err = _make_http_error(500, "internal error")
    mock_open.side_effect = [err, err]
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    with patch("time.sleep"), pytest.raises(DatadogError, match="500"):
        client.logs_search("*", "now-1h", "now")


@patch("urllib.request.urlopen")
def test_4xx_raises_immediately(mock_open):
    mock_open.side_effect = _make_http_error(403, "forbidden")
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    with pytest.raises(DatadogError, match="403"):
        client.logs_search("*", "now-1h", "now")


@patch("urllib.request.urlopen")
def test_headers_injected(mock_open):
    mock_open.return_value = _make_response(LOGS_RESP)
    client = DatadogClient(site="datadoghq.com", api_key="mykey", app_key="myapp")
    client.logs_search("*", "now-1h", "now")
    req = mock_open.call_args[0][0]
    assert req.get_header("Dd-api-key") == "mykey"
    assert req.get_header("Dd-application-key") == "myapp"


@patch("urllib.request.urlopen")
def test_site_used_in_url(mock_open):
    mock_open.return_value = _make_response(LOGS_RESP)
    client = DatadogClient(site="datadoghq.eu", api_key="k", app_key="a")
    client.logs_search("*", "now-1h", "now")
    req = mock_open.call_args[0][0]
    assert "datadoghq.eu" in req.full_url


@patch("urllib.request.urlopen")
def test_aggregate_parse(mock_open):
    mock_open.return_value = _make_response(AGG_RESP)
    client = DatadogClient(site="datadoghq.com", api_key="k", app_key="a")
    rows = client.logs_aggregate("*", "now-1h", "now", group_by=["service", "status"])
    assert len(rows) == 1
    assert rows[0].groups == {"service": "ms-foo", "status": "error"}
    assert rows[0].value == 42.0
