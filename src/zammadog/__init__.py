"""zammadog — token-friendly Datadog Logs/APM client."""
from .client import DatadogClient, DatadogError
from .compact import AggregateRow, CompactLog, CompactSpan
from .evidence import gather_evidence
from .links import DatadogLink, extract_datadog_links

__all__ = [
    "DatadogClient",
    "DatadogError",
    "CompactLog",
    "CompactSpan",
    "AggregateRow",
    "DatadogLink",
    "extract_datadog_links",
    "gather_evidence",
]
