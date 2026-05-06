"""Tests for CLI entry point."""
from __future__ import annotations
import json
from unittest.mock import MagicMock, patch

import pytest

from zammadog.cli import main
from zammadog.compact import AggregateRow, CompactLog, CompactSpan


LOG_ROW = CompactLog(
    ts="2026-05-05T12:00:00Z", svc="ms-foo", status="error",
    msg="boom", trace_id="t1", error_kind=None
)
SPAN_ROW = CompactSpan(
    ts="2026-05-05T12:00:00Z", svc="ms-foo", op="http.get", resource="GET /",
    duration_ms=5, status="0", trace_id="t1", error_type=None
)
AGG_ROW = AggregateRow(groups={"service": "ms-foo"}, value=10)


def _env():
    return {"DD_API_KEY": "k", "DD_APP_KEY": "a", "DD_SITE": "datadoghq.com"}


@patch("zammadog.client.DatadogClient.logs_search", return_value=[LOG_ROW])
@patch.dict("os.environ", {"DD_API_KEY": "k", "DD_APP_KEY": "a"})
def test_logs_search_table(mock_search, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["logs", "search", "--query", "service:ms-foo"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "ms-foo" in out
    assert "error" in out


@patch("zammadog.client.DatadogClient.logs_search", return_value=[LOG_ROW])
@patch.dict("os.environ", {"DD_API_KEY": "k", "DD_APP_KEY": "a"})
def test_logs_search_json(mock_search, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["logs", "search", "--query", "*", "--json"])
    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["svc"] == "ms-foo"


@patch("zammadog.client.DatadogClient.apm_search", return_value=[SPAN_ROW])
@patch.dict("os.environ", {"DD_API_KEY": "k", "DD_APP_KEY": "a"})
def test_apm_search_table(mock_search, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["apm", "search", "--query", "service:ms-foo"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "ms-foo" in out


@patch.dict("os.environ", {"DD_API_KEY": "", "DD_APP_KEY": ""})
def test_missing_api_key_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["logs", "search", "--query", "*"])
    assert exc.value.code == 1


def test_no_subcommand_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
