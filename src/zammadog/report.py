"""Parser-driven report framework.

A parser may implement an optional ``report(rows) -> ReportModel`` hook to provide
business-specific analysis (top error codes, endpoints, etc.). When a parser does
not implement the hook, :func:`build_generic_report` is used as a deterministic
fallback that clusters messages by masking digits, hex tokens, and UUIDs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .compact import CompactLog


@dataclass(frozen=True)
class KPI:
    label: str
    value: str
    tone: str = "ok"  # ok|red|amber|blue → CSS badge classes already in _REPORT_CSS


@dataclass(frozen=True)
class Chart:
    title: str
    bars: list[tuple[str, float]]  # horizontal bars; client-side renders width


@dataclass(frozen=True)
class TableSection:
    title: str
    columns: list[str]
    rows: list[list]  # client-side auto-detects numeric vs string columns for sort/filter


@dataclass(frozen=True)
class ReportModel:
    title: str
    kpis: list[KPI]
    charts: list[Chart]
    sections: list[TableSection]


@runtime_checkable
class ReportingParser(Protocol):
    """Optional hook a parser may implement to drive the report."""

    def report(self, rows: list[CompactLog]) -> ReportModel:
        ...


# Mask digits, hex tokens (10+ hex chars), and UUIDs to a single placeholder so
# similar messages collapse into the same cluster regardless of run-time data.
_DIGIT_RE = re.compile(r"\d+")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{10,}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_MASK = "#"


def _signature(msg: str) -> str:
    msg = _UUID_RE.sub(_MASK, msg)
    msg = _HEX_RE.sub(_MASK, msg)
    msg = _DIGIT_RE.sub(_MASK, msg)
    return msg.strip()


def build_generic_report(rows: list[CompactLog]) -> ReportModel:
    """Generic fallback: cluster by masked message signature, count, top errors/warns."""
    if not rows:
        return ReportModel(
            title="(no results)",
            kpis=[KPI("Total", "0")],
            charts=[],
            sections=[],
        )

    sig_counts: dict[str, int] = {}
    sig_sample: dict[str, str] = {}
    for r in rows:
        sig = _signature(r.msg)
        sig_counts[sig] = sig_counts.get(sig, 0) + 1
        sig_sample.setdefault(sig, r.msg[:200])

    total_errors = sum(1 for r in rows if (r.status or "").upper() in ("ERROR", "FATAL"))
    total_warns = sum(1 for r in rows if (r.status or "").upper() == "WARN")

    top = sorted(sig_counts.items(), key=lambda x: -x[1])[:15]

    section_rows = [
        [count, sig_sample[sig], sig[:120]]
        for sig, count in top
    ]

    return ReportModel(
        title=f"CloudWatch logs — {len(rows)} lines, {len(sig_counts)} clusters",
        kpis=[
            KPI("Total lines", str(len(rows))),
            KPI("Distinct clusters", str(len(sig_counts))),
            KPI("Errors", str(total_errors), tone="red" if total_errors else "ok"),
            KPI("Warnings", str(total_warns), tone="amber" if total_warns else "ok"),
        ],
        charts=[
            Chart("Top message clusters", [(sig[:60], float(count)) for sig, count in top]),
        ],
        sections=[
            TableSection(
                title="Message clusters",
                columns=["COUNT", "SAMPLE", "SIGNATURE"],
                rows=section_rows,
            ),
        ],
    )
