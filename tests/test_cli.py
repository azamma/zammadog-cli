"""Tests for CLI entry point."""
from __future__ import annotations
import json
from unittest.mock import MagicMock, patch

import pytest

from zammadog.cli import main
from zammadog.compact import AggregateRow, CompactLog, CompactMetric, CompactSpan


LOG_ROW = CompactLog(
    ts="2026-05-05T12:00:00Z", svc="ms-foo", status="error",
    msg="boom", trace_id="t1", error_kind=None
)
SPAN_ROW = CompactSpan(
    ts="2026-05-05T12:00:00Z", svc="ms-foo", op="http.get", resource="GET /",
    duration_ms=5, status="0", trace_id="t1", error_type=None
)
AGG_ROW = AggregateRow(groups={"service": "ms-foo"}, value=10)
METRIC_ROW = CompactMetric(ts="2026-05-05T12:00:00Z", label="Errors", value=1.5)


def _env():
    return {"DD_API_KEY": "k", "DD_APP_KEY": "a", "DD_SITE": "datadoghq.com"}


@pytest.fixture(autouse=True)
def _reset_clients():
    """Reset lazy client globals between tests."""
    import zammadog.cli as _cli
    _cli._CLIENT = None
    _cli._CW_CLIENT = None
    yield


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


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_search_table(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [
                {"field": "@timestamp", "value": "2026-05-05T12:00:00.000Z"},
                {"field": "@message", "value": "boom"},
                {"field": "@logStream", "value": "my-stream"},
            ]
        ],
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-search",
            "-q", "fields @timestamp, @message",
            "-g", "/aws/lambda/foo",
        ])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "boom" in out


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_search_json(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [
                {"field": "@timestamp", "value": "2026-05-05T12:00:00.000Z"},
                {"field": "@message", "value": "boom"},
                {"field": "@logStream", "value": "my-stream"},
            ]
        ],
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-search",
            "-q", "fields @timestamp, @message",
            "-g", "/aws/lambda/foo",
            "--json",
        ])
    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["svc"] == "my-stream"


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_aggregate_table(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [
                {"field": "level", "value": "error"},
                {"field": "count(*)", "value": "42"},
            ]
        ],
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-search",
            "-q", "stats count(*) by level",
            "-g", "/aws/lambda/foo",
        ])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "error" in out
    assert "42" in out


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_filter_table(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.filter_log_events.return_value = {
        "events": [
            {
                "timestamp": 1714908000000,
                "message": "Filtered event",
                "logStreamName": "my-stream",
            }
        ]
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-filter",
            "-g", "/aws/lambda/foo",
            "-p", "ERROR",
        ])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Filtered event" in out


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_logs_filter_json(mock_boto3_client, capsys):
    logs_mock = MagicMock()
    logs_mock.filter_log_events.return_value = {
        "events": [
            {
                "timestamp": 1714908000000,
                "message": "Filtered event",
                "logStreamName": "my-stream",
            }
        ]
    }
    mock_boto3_client.side_effect = lambda svc, **kw: logs_mock if svc == "logs" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-filter",
            "-g", "/aws/lambda/foo",
            "--json",
        ])
    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["msg"] == "Filtered event"


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_metrics_table(mock_boto3_client, capsys):
    cw_mock = MagicMock()
    cw_mock.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "Timestamps": [],
                "Values": [],
                "Label": "Errors",
            }
        ]
    }
    mock_boto3_client.side_effect = lambda svc, **kw: cw_mock if svc == "cloudwatch" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "metrics",
            "-n", "AWS/Lambda",
            "-m", "Errors",
        ])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "(no results)" in out


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_metrics_with_dimension(mock_boto3_client, capsys):
    cw_mock = MagicMock()
    cw_mock.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "Timestamps": [],
                "Values": [],
                "Label": "Errors",
            }
        ]
    }
    mock_boto3_client.side_effect = lambda svc, **kw: cw_mock if svc == "cloudwatch" else MagicMock()
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "metrics",
            "-n", "AWS/Lambda",
            "-m", "Errors",
            "-d", "FunctionName=my-fn",
        ])
    assert exc.value.code == 0
    call = cw_mock.get_metric_data.call_args[1]
    dims = call["MetricDataQueries"][0]["MetricStat"]["Metric"]["Dimensions"]
    assert dims == [{"Name": "FunctionName", "Value": "my-fn"}]


@patch("zammadog.cloudwatch_client.boto3.client")
def test_cw_no_region_exits_1(mock_boto3_client, capsys):
    from botocore.exceptions import NoRegionError

    mock_boto3_client.side_effect = NoRegionError(service_name="logs")
    with pytest.raises(SystemExit) as exc:
        main([
            "cw", "logs-search",
            "-q", "fields @timestamp, @message",
            "-g", "/aws/lambda/foo",
        ])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "AWS region not resolved" in err
