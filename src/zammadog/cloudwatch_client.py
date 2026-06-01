"""AWS CloudWatch client — Logs Insights, filter-log-events, and Metrics."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import boto3
from botocore.exceptions import NoRegionError

from .client import MAX_LIMIT, MAX_WINDOW_HOURS, DatadogError, _rel_to_epoch_ms, _window_guard
from .compact import AggregateRow, CompactLog, CompactLogGroup, CompactMetric, compact_cw_log

POLL_MAX = 30
POLL_INTERVAL_S = 1.0
DEFAULT_LIMIT = 25
# A distributed trace is one ordered stream — the 50-row search guard is too small,
# so trace() allows many more lines (Insights start_query itself caps at 10000).
TRACE_MAX = 1000


class CloudWatchError(Exception):
    """Error raised for CloudWatch API failures or configuration issues."""

    def __init__(self, message: str, body: str = "") -> None:
        super().__init__(message)
        self.body = body


def _to_epoch_seconds(t: str) -> int:
    """Convert a time spec to epoch seconds for start_query."""
    return _rel_to_epoch_ms(t) // 1000


def _to_epoch_ms(t: str) -> int:
    """Convert a time spec to epoch milliseconds for filter_log_events."""
    return _rel_to_epoch_ms(t)


def _to_utc_datetime(t: str) -> datetime:
    """Convert a time spec to a timezone-aware UTC datetime for get_metric_data."""
    return datetime.fromtimestamp(_rel_to_epoch_ms(t) / 1000, tz=timezone.utc)


@dataclass
class CloudWatchClient:
    """Client for AWS CloudWatch Logs and Metrics queries.

    Attributes:
        logs: Boto3 CloudWatch Logs client.
        cloudwatch: Boto3 CloudWatch Metrics client.
    """

    logs: object = field(init=False)
    cloudwatch: object = field(init=False)

    @classmethod
    def from_env(cls) -> "CloudWatchClient":
        """Create a client from the environment using boto3 default credentials.

        Returns:
            An initialised CloudWatchClient.

        Raises:
            CloudWatchError: If the AWS region cannot be resolved.
        """
        instance = cls.__new__(cls)
        try:
            instance.logs = boto3.client("logs")
            instance.cloudwatch = boto3.client("cloudwatch")
        except NoRegionError as exc:
            raise CloudWatchError(
                "AWS region not resolved. Set AWS_REGION or configure ~/.aws/config."
            ) from exc
        return instance

    def log_groups(
        self,
        pattern: str | None = None,
        *,
        limit: int = 50,
    ) -> list[CompactLogGroup]:
        """List log groups, optionally filtered by a name substring.

        Args:
            pattern: Case-sensitive substring to match within log group names.
                When None, returns groups in the account/region.
            limit: Max groups to return (API caps a single page at 50).

        Returns:
            List of CompactLogGroup rows.

        Raises:
            CloudWatchError: On API failure.
        """
        kwargs: dict = {"limit": min(limit, 50)}
        if pattern:
            kwargs["logGroupNamePattern"] = pattern

        try:
            resp = self.logs.describe_log_groups(**kwargs)
        except Exception as exc:
            raise CloudWatchError(f"Failed to describe log groups: {exc}") from exc

        rows: list[CompactLogGroup] = []
        for g in (resp.get("logGroups") or []):
            rows.append(
                CompactLogGroup(
                    name=g.get("logGroupName", ""),
                    stored_mb=round((g.get("storedBytes") or 0) / 1_048_576, 1),
                    retention_days=g.get("retentionInDays"),
                )
            )
        return rows

    def trace(
        self,
        trace_id: str,
        from_ts: str,
        to_ts: str,
        *,
        groups_pattern: str | None = None,
        limit: int = 300,
    ) -> tuple[list[CompactLog], list[str]]:
        """Search a trace id across many log groups via one Insights query.

        Args:
            trace_id: The trace id to grep for (substring match on @message).
            from_ts: Start time spec.
            to_ts: End time spec.
            groups_pattern: Case-sensitive substring to select log groups. None
                searches the first 50 groups in the account/region.
            limit: Max matching lines to return.

        Returns:
            (rows sorted by timestamp ascending, names of the searched groups).

        Raises:
            CloudWatchError: If no log groups match, or on API failure.
        """
        groups = [g.name for g in self.log_groups(groups_pattern, limit=50)]
        if not groups:
            raise CloudWatchError("No log groups matched the pattern.")
        # Insights caps a single query at 50 log groups.
        groups = groups[:50]
        safe_id = "".join(c for c in trace_id if c.isalnum())
        query = (
            f'fields @timestamp, @log, @message '
            f'| filter @message like "{safe_id}" '
            f'| sort @timestamp asc'
        )
        rows = self.logs_insights(query, from_ts, to_ts, log_groups=groups, limit=limit, max_cap=TRACE_MAX)
        return rows, groups  # type: ignore[return-value]

    def logs_insights(
        self,
        query: str,
        from_ts: str,
        to_ts: str,
        *,
        log_groups: list[str],
        limit: int = DEFAULT_LIMIT,
        max_cap: int = MAX_LIMIT,
    ) -> list[CompactLog] | list[AggregateRow]:
        """Run a CloudWatch Logs Insights query with bounded polling.

        Args:
            query: The Insights query string.
            from_ts: Start time spec.
            to_ts: End time spec.
            log_groups: List of log group names to query.
            limit: Max results to return.

        Returns:
            CompactLog rows for message queries, or AggregateRow rows for stats queries.

        Raises:
            CloudWatchError: On query failure, terminal non-Complete status, or
                if polling is exhausted without completion.
        """
        limit = min(limit, max_cap)
        try:
            _window_guard(from_ts, to_ts)
        except DatadogError as exc:
            raise CloudWatchError(str(exc)) from exc
        start_time = _to_epoch_seconds(from_ts)
        end_time = _to_epoch_seconds(to_ts)

        try:
            resp = self.logs.start_query(
                logGroupNames=log_groups,
                startTime=start_time,
                endTime=end_time,
                queryString=query,
                limit=limit,
            )
        except Exception as exc:
            raise CloudWatchError(f"Failed to start Insights query: {exc}") from exc

        query_id = resp["queryId"]
        for _ in range(POLL_MAX):
            try:
                result = self.logs.get_query_results(queryId=query_id)
            except Exception as exc:
                raise CloudWatchError(f"Failed to get query results: {exc}") from exc

            status = result.get("status", "Unknown")
            if status == "Complete":
                return self._parse_insights_results(result.get("results") or [], limit)
            if status in ("Failed", "Cancelled", "Timeout"):
                raise CloudWatchError(f"Insights query terminated with status: {status}")
            time.sleep(POLL_INTERVAL_S)

        raise CloudWatchError("Insights query polling exhausted without completion.")

    def _parse_insights_results(
        self, rows: list[list[dict]], limit: int
    ) -> list[CompactLog] | list[AggregateRow]:
        """Parse Insights result rows into CompactLog or AggregateRow."""
        results: list[CompactLog] | list[AggregateRow] = []
        for raw in rows[:limit]:
            row = {field["field"]: field["value"] for field in raw}
            row.pop("@ptr", None)
            if "@message" in row:
                results.append(compact_cw_log(row))
            else:
                results.append(self._parse_stats_row(row))
        return results

    @staticmethod
    def _parse_stats_row(row: dict) -> AggregateRow:
        """Parse a stats query row into AggregateRow.

        The value column is the one that parses as a float; all other columns
        become group keys.  If a numeric field is also a ``by`` field it will
        still be treated as a group, which matches standard Insights behaviour.
        """
        float_col: str | None = None
        groups: dict[str, str] = {}
        for key, val in row.items():
            if float_col is None:
                try:
                    float(val)
                    float_col = key
                    continue
                except (ValueError, TypeError):
                    pass
            groups[key] = val
        value = float(row[float_col]) if float_col is not None else 0.0
        return AggregateRow(groups=groups, value=value)

    def logs_filter(
        self,
        log_group: str,
        pattern: str,
        from_ts: str,
        to_ts: str,
        *,
        limit: int = DEFAULT_LIMIT,
    ) -> list[CompactLog]:
        """Filter log events in a single log group.

        Args:
            log_group: Name of the log group to query.
            pattern: CloudWatch filter pattern (empty string matches all).
            from_ts: Start time spec.
            to_ts: End time spec.
            limit: Max events to return.

        Returns:
            List of CompactLog rows.

        Raises:
            CloudWatchError: On API failure.
        """
        limit = min(limit, MAX_LIMIT)
        try:
            _window_guard(from_ts, to_ts)
        except DatadogError as exc:
            raise CloudWatchError(str(exc)) from exc
        start_time = _to_epoch_ms(from_ts)
        end_time = _to_epoch_ms(to_ts)

        try:
            resp = self.logs.filter_log_events(
                logGroupName=log_group,
                filterPattern=pattern,
                startTime=start_time,
                endTime=end_time,
                limit=min(limit, MAX_LIMIT),
            )
        except Exception as exc:
            raise CloudWatchError(f"Failed to filter log events: {exc}") from exc

        return [compact_cw_log(e) for e in (resp.get("events") or [])]

    def metrics(
        self,
        namespace: str,
        metric_name: str,
        from_ts: str,
        to_ts: str,
        *,
        dimensions: dict | None = None,
        stat: str = "Average",
        period: int = 300,
    ) -> list[CompactMetric]:
        """Fetch CloudWatch metric data points.

        Args:
            namespace: CloudWatch metric namespace (e.g. ``AWS/Lambda``).
            metric_name: Name of the metric.
            from_ts: Start time spec.
            to_ts: End time spec.
            dimensions: Optional dimension filter as ``{Name: Value}``.
            stat: Statistic to retrieve (e.g. ``Average``, ``Sum``).
            period: Granularity in seconds.

        Returns:
            List of CompactMetric rows, one per datapoint.

        Raises:
            CloudWatchError: On API failure.
        """
        try:
            _window_guard(from_ts, to_ts)
        except DatadogError as exc:
            raise CloudWatchError(str(exc)) from exc
        start_time = _to_utc_datetime(from_ts)
        end_time = _to_utc_datetime(to_ts)

        metric_stat = {
            "Metric": {
                "Namespace": namespace,
                "MetricName": metric_name,
            },
            "Period": period,
            "Stat": stat,
        }
        if dimensions:
            metric_stat["Metric"]["Dimensions"] = [
                {"Name": k, "Value": v} for k, v in dimensions.items()
            ]

        try:
            resp = self.cloudwatch.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "m1",
                        "MetricStat": metric_stat,
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
            )
        except Exception as exc:
            raise CloudWatchError(f"Failed to get metric data: {exc}") from exc

        metric_results = (resp.get("MetricDataResults") or [])
        if not metric_results:
            return []

        result = metric_results[0]
        timestamps = result.get("Timestamps") or []
        values = result.get("Values") or []
        label = result.get("Label", metric_name)

        rows: list[CompactMetric] = []
        for ts, val in zip(timestamps, values):
            ts_iso = ts.isoformat().replace("+00:00", "Z") if isinstance(ts, datetime) else str(ts)
            rows.append(
                CompactMetric(
                    ts=ts_iso,
                    label=label,
                    value=float(val),
                )
            )
        return rows
