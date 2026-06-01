"""Tests for CloudWatchClient."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from zammadog.cloudwatch_client import (
    CloudWatchClient,
    CloudWatchError,
    DEFAULT_LIMIT,
    POLL_MAX,
    _to_epoch_ms,
    _to_epoch_seconds,
    _to_utc_datetime,
)
from zammadog.compact import AggregateRow, CompactLog, CompactMetric


def _boto3_client_factory(logs_mock: MagicMock, cw_mock: MagicMock):
    """Return a side_effect for ``boto3.client`` that routes by service name."""

    def _side_effect(service_name, **kwargs):
        if service_name == "logs":
            return logs_mock
        if service_name == "cloudwatch":
            return cw_mock
        raise RuntimeError(f"Unexpected service: {service_name}")

    return _side_effect


@patch("zammadog.cloudwatch_client.boto3.client")
def test_from_env_no_region(mock_boto3_client):
    from botocore.exceptions import NoRegionError

    mock_boto3_client.side_effect = NoRegionError(service_name="logs")
    with pytest.raises(CloudWatchError, match="AWS region not resolved"):
        CloudWatchClient.from_env()


@patch("zammadog.cloudwatch_client.time.sleep")
@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_insights_messages(mock_boto3_client, mock_sleep):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [
                {"field": "@timestamp", "value": "2026-05-05T12:00:00.000Z"},
                {"field": "@message", "value": "boom"},
                {"field": "@logStream", "value": "stream-a"},
            ]
        ],
    }
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows = client.logs_insights(
        "fields @timestamp, @message | filter @message like /boom/",
        "now-1h",
        "now",
        log_groups=["/aws/lambda/foo"],
    )

    assert len(rows) == 1
    assert isinstance(rows[0], CompactLog)
    assert rows[0].msg == "boom"
    assert rows[0].svc == "stream-a"

    # Verify epoch seconds were passed
    call = logs_mock.start_query.call_args[1]
    assert call["startTime"] == _to_epoch_seconds("now-1h")
    assert call["endTime"] == _to_epoch_seconds("now")


@patch("zammadog.cloudwatch_client.time.sleep")
@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_insights_stats(mock_boto3_client, mock_sleep):
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
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows = client.logs_insights(
        "stats count(*) by level",
        "now-1h",
        "now",
        log_groups=["/aws/lambda/foo"],
    )

    assert len(rows) == 1
    assert isinstance(rows[0], AggregateRow)
    assert rows[0].groups == {"level": "error"}
    assert rows[0].value == 42.0


@patch("zammadog.cloudwatch_client.time.sleep")
@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_insights_running_then_complete(mock_boto3_client, mock_sleep):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.side_effect = [
        {"status": "Running", "results": []},
        {"status": "Complete", "results": []},
    ]
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows = client.logs_insights(
        "fields @timestamp, @message",
        "now-1h",
        "now",
        log_groups=["/aws/lambda/foo"],
    )
    assert rows == []
    assert logs_mock.get_query_results.call_count == 2


@patch("zammadog.cloudwatch_client.time.sleep")
@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_insights_failed_raises(mock_boto3_client, mock_sleep):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {"status": "Failed", "results": []}
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    with pytest.raises(CloudWatchError, match="Failed"):
        client.logs_insights(
            "fields @timestamp, @message",
            "now-1h",
            "now",
            log_groups=["/aws/lambda/foo"],
        )


@patch("zammadog.cloudwatch_client.time.sleep")
@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_insights_poll_exhausted_raises(mock_boto3_client, mock_sleep):
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {"status": "Running", "results": []}
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    with pytest.raises(CloudWatchError, match="polling exhausted"):
        client.logs_insights(
            "fields @timestamp, @message",
            "now-1h",
            "now",
            log_groups=["/aws/lambda/foo"],
        )
    assert logs_mock.get_query_results.call_count == POLL_MAX


@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_filter(mock_boto3_client):
    logs_mock = MagicMock()
    logs_mock.filter_log_events.return_value = {
        "events": [
            {
                "timestamp": 1714908000000,
                "message": "Filtered event",
                "logStreamName": "stream-b",
            }
        ]
    }
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows = client.logs_filter(
        "/aws/lambda/foo",
        "ERROR",
        "now-1h",
        "now",
    )

    assert len(rows) == 1
    assert isinstance(rows[0], CompactLog)
    assert rows[0].msg == "Filtered event"

    call = logs_mock.filter_log_events.call_args[1]
    assert call["startTime"] == _to_epoch_ms("now-1h")
    assert call["endTime"] == _to_epoch_ms("now")
    assert call["logGroupName"] == "/aws/lambda/foo"
    assert call["filterPattern"] == "ERROR"


@patch("zammadog.cloudwatch_client.boto3.client")
def test_logs_filter_time_unit_guard(mock_boto3_client):
    """Assert the 1000x difference between Insights seconds and filter ms."""
    logs_mock = MagicMock()
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {"status": "Complete", "results": []}
    logs_mock.filter_log_events.return_value = {"events": []}
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    client.logs_insights(
        "fields @timestamp, @message",
        "2026-05-05T10:00:00Z",
        "2026-05-05T11:00:00Z",
        log_groups=["/aws/lambda/foo"],
    )
    client.logs_filter(
        "/aws/lambda/foo",
        "",
        "2026-05-05T10:00:00Z",
        "2026-05-05T11:00:00Z",
    )

    insights_start = logs_mock.start_query.call_args[1]["startTime"]
    filter_start = logs_mock.filter_log_events.call_args[1]["startTime"]
    assert filter_start == insights_start * 1000


@patch("zammadog.cloudwatch_client.boto3.client")
def test_metrics(mock_boto3_client):
    cw_mock = MagicMock()
    cw_mock.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "Timestamps": [datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)],
                "Values": [1.5],
                "Label": "Errors",
            }
        ]
    }
    mock_boto3_client.side_effect = _boto3_client_factory(MagicMock(), cw_mock)

    client = CloudWatchClient.from_env()
    rows = client.metrics(
        "AWS/Lambda",
        "Errors",
        "now-1h",
        "now",
        dimensions={"FunctionName": "my-fn"},
        stat="Sum",
        period=60,
    )

    assert len(rows) == 1
    assert isinstance(rows[0], CompactMetric)
    assert rows[0].ts == "2026-05-05T12:00:00Z"
    assert rows[0].label == "Errors"
    assert rows[0].value == 1.5

    call = cw_mock.get_metric_data.call_args[1]
    assert isinstance(call["StartTime"], datetime)
    assert call["StartTime"].tzinfo is not None
    assert call["MetricDataQueries"][0]["MetricStat"]["Metric"]["Dimensions"] == [
        {"Name": "FunctionName", "Value": "my-fn"}
    ]


@patch("zammadog.cloudwatch_client.boto3.client")
def test_window_cap_rejected(mock_boto3_client):
    mock_boto3_client.side_effect = _boto3_client_factory(MagicMock(), MagicMock())
    client = CloudWatchClient.from_env()
    with pytest.raises(CloudWatchError, match="exceeds max"):
        client.logs_insights(
            "fields @timestamp, @message",
            "now-25h",
            "now",
            log_groups=["/aws/lambda/foo"],
        )


@patch("zammadog.cloudwatch_client.boto3.client")
def test_from_env_no_region(mock_boto3_client):
    from botocore.exceptions import NoRegionError

    mock_boto3_client.side_effect = NoRegionError(service_name="logs")
    with pytest.raises(CloudWatchError, match="AWS region not resolved"):
        CloudWatchClient.from_env()


@patch("zammadog.cloudwatch_client.boto3.client")
def test_log_groups_maps(mock_boto3_client):
    logs_mock = MagicMock()
    logs_mock.describe_log_groups.return_value = {
        "logGroups": [
            {"logGroupName": "/aws/ecs/my-service", "storedBytes": 2_097_152, "retentionInDays": 30},
            {"logGroupName": "/aws/ecs/other-service", "storedBytes": 0},
        ]
    }
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows = client.log_groups("service", limit=10)

    assert [r.name for r in rows] == ["/aws/ecs/my-service", "/aws/ecs/other-service"]
    assert rows[0].stored_mb == 2.0
    assert rows[0].retention_days == 30
    assert rows[1].retention_days is None  # never expires
    # pattern forwarded, limit capped at 50
    call = logs_mock.describe_log_groups.call_args[1]
    assert call["logGroupNamePattern"] == "service"
    assert call["limit"] == 10


@patch("zammadog.cloudwatch_client.boto3.client")
def test_log_groups_no_pattern_omits_kwarg(mock_boto3_client):
    logs_mock = MagicMock()
    logs_mock.describe_log_groups.return_value = {"logGroups": []}
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows = client.log_groups(None, limit=100)

    assert rows == []
    call = logs_mock.describe_log_groups.call_args[1]
    assert "logGroupNamePattern" not in call
    assert call["limit"] == 50  # capped


@patch("zammadog.cloudwatch_client.time.sleep")
@patch("zammadog.cloudwatch_client.boto3.client")
def test_trace_across_groups(mock_boto3_client, mock_sleep):
    logs_mock = MagicMock()
    logs_mock.describe_log_groups.return_value = {
        "logGroups": [{"logGroupName": "svc-a"}, {"logGroupName": "svc-b"}]
    }
    logs_mock.start_query.return_value = {"queryId": "q1"}
    logs_mock.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [
                {"field": "@timestamp", "value": "2026-06-01T00:00:01.000Z"},
                {"field": "@log", "value": "123456789012:svc-a"},
                {"field": "@message", "value": "origin TID123"},
            ]
        ],
    }
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())

    client = CloudWatchClient.from_env()
    rows, groups = client.trace("TID123", "now-1h", "now", groups_pattern="svc")

    assert groups == ["svc-a", "svc-b"]
    assert rows[0].svc == "svc-a"  # @log account prefix stripped
    # both groups passed to the single Insights query, trace id sanitised into filter
    sq = logs_mock.start_query.call_args[1]
    assert sq["logGroupNames"] == ["svc-a", "svc-b"]
    assert 'like "TID123"' in sq["queryString"]


@patch("zammadog.cloudwatch_client.boto3.client")
def test_trace_no_groups_raises(mock_boto3_client):
    logs_mock = MagicMock()
    logs_mock.describe_log_groups.return_value = {"logGroups": []}
    mock_boto3_client.side_effect = _boto3_client_factory(logs_mock, MagicMock())
    client = CloudWatchClient.from_env()
    with pytest.raises(CloudWatchError, match="No log groups matched"):
        client.trace("TID", "now-1h", "now", groups_pattern="zzz")
