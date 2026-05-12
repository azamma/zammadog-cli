"""zammadog CLI — argparse entry point."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict

from .client import DatadogClient, DatadogError, RateLimit
from .evidence import gather_evidence
from .links import extract_datadog_links
from .render import render_aggregate, render_endpoint_report, render_endpoint_report_ai, render_endpoint_report_html, render_logs_table, render_spans_table, render_trace_stats, render_trace_summary

VERSION = "0.1.0"

_CLIENT: DatadogClient | None = None


def _client() -> DatadogClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    try:
        _CLIENT = DatadogClient.from_env()
        return _CLIENT
    except DatadogError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _print_rate_limit(rl: RateLimit | None, force: bool) -> None:
    if rl is None or rl.limit == 0:
        return
    low = rl.pct_remaining < 0.10
    if not (force or low):
        return
    tag = "WARN" if low else "rate"
    period = f"/{rl.period_s}s" if rl.period_s else ""
    print(
        f"[{tag}: {rl.remaining}/{rl.limit}{period}, reset {rl.reset_s}s]",
        file=sys.stderr,
    )


def _dump(obj: list, use_json: bool, render_fn) -> None:
    if use_json:
        print(json.dumps([asdict(r) for r in obj], indent=2))
    else:
        print(render_fn(obj))


def cmd_logs_search(args: argparse.Namespace) -> int:
    rows = _client().logs_search(
        args.query,
        args.from_ts,
        args.to_ts,
        limit=args.limit,
    )
    _dump(rows, args.json, render_logs_table)
    return 0


def cmd_logs_aggregate(args: argparse.Namespace) -> int:
    group_by = [g.strip() for g in args.group_by.split(",")]
    rows = _client().logs_aggregate(
        args.query,
        args.from_ts,
        args.to_ts,
        group_by=group_by,
        compute=args.compute,
    )
    _dump(rows, args.json, render_aggregate)
    return 0


def cmd_apm_search(args: argparse.Namespace) -> int:
    rows = _client().apm_search(
        args.query,
        args.from_ts,
        args.to_ts,
        limit=args.limit,
    )
    _dump(rows, args.json, render_spans_table)
    return 0


def cmd_apm_trace(args: argparse.Namespace) -> int:
    spans = _client().apm_search_all(
        f"trace_id:{args.trace_id}",
        args.from_ts,
        args.to_ts,
    )
    if args.json:
        print(json.dumps([asdict(s) for s in spans], indent=2))
    elif args.stats:
        print(render_trace_stats(spans))
    else:
        print(render_trace_summary(spans))
    return 0


def cmd_apm_endpoint_report(args: argparse.Namespace) -> int:
    use_html = getattr(args, "html", False)
    use_ai = getattr(args, "ai", False)
    use_json = args.json

    flags = sum([use_html, use_ai, use_json])
    if flags > 1:
        print("Error: --html, --ai, and --json are mutually exclusive", file=sys.stderr)
        return 2

    client = _client()
    endpoints = args.endpoints if args.endpoints else [args.endpoint]

    if use_html:
        sections: list[str] = []
        for ep in endpoints:
            spans, n = client.endpoint_report_spans(
                ep, args.from_ts, args.to_ts, service=args.service, sample=args.sample
            )
            sections.append(render_endpoint_report_html(
                spans, n, ep, args.service, args.from_ts, args.to_ts
            ))
        output = "\n".join(sections)
        out_path = getattr(args, "out", None)
        if out_path:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
        else:
            print(output)
        return 0

    if use_ai:
        parts: list[str] = []
        for ep in endpoints:
            spans, n = client.endpoint_report_spans(
                ep, args.from_ts, args.to_ts, service=args.service, sample=args.sample
            )
            parts.append(render_endpoint_report_ai(
                spans, n, ep, args.service, args.from_ts, args.to_ts
            ))
        content = "\n\n---\n\n".join(parts)
        key = hashlib.sha1(
            ("|".join(endpoints) + args.from_ts + args.to_ts).encode()
        ).hexdigest()[:8]
        tmp_dir = os.path.expanduser("~/.claude/tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        out_path = os.path.join(tmp_dir, f"er_{key}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(out_path)
        return 0

    for i, ep in enumerate(endpoints):
        if i > 0:
            print()
        spans, n = client.endpoint_report_spans(
            ep, args.from_ts, args.to_ts, service=args.service, sample=args.sample
        )
        if use_json:
            print(json.dumps({"endpoint": ep, "traces": n, "spans": [asdict(s) for s in spans]}, indent=2))
        else:
            print(render_endpoint_report(spans, n, ep, args.service))
    return 0


def cmd_apm_aggregate(args: argparse.Namespace) -> int:
    group_by = [g.strip() for g in args.group_by.split(",")]
    rows = _client().apm_aggregate(
        args.query,
        args.from_ts,
        args.to_ts,
        group_by=group_by,
        compute=args.compute,
    )
    _dump(rows, args.json, render_aggregate)
    return 0


def cmd_from_url(args: argparse.Namespace) -> int:
    links = extract_datadog_links(args.url)
    if not links:
        print(f"No Datadog URL found in: {args.url!r}", file=sys.stderr)
        return 1
    client = _client()
    for i, link in enumerate(links, 1):
        block = gather_evidence(client, link, link_num=i)
        print(block)
        if i < len(links):
            print()
    return 0


def _add_time_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from", dest="from_ts", default="now-1h", metavar="TIME")
    p.add_argument("--to", dest="to_ts", default="now", metavar="TIME")


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="Output JSON instead of table")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="zammadog",
        description="Token-friendly Datadog Logs/APM CLI.",
    )
    parser.add_argument("--version", action="version", version=f"zammadog {VERSION}")
    parser.add_argument(
        "--show-limit",
        action="store_true",
        help="Print Datadog rate-limit headers to stderr after request",
    )

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--show-limit",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print Datadog rate-limit headers to stderr after request",
    )

    sub = parser.add_subparsers(dest="resource")

    # --- logs ---
    logs_p = sub.add_parser("logs")
    logs_sub = logs_p.add_subparsers(dest="action")

    ls_p = logs_sub.add_parser("search", parents=[common])
    ls_p.add_argument("--query", "-q", required=True)
    ls_p.add_argument("--limit", type=int, default=25)
    _add_time_args(ls_p)
    _add_json(ls_p)
    ls_p.set_defaults(func=cmd_logs_search)

    la_p = logs_sub.add_parser("aggregate", parents=[common])
    la_p.add_argument("--query", "-q", required=True)
    la_p.add_argument("--group-by", required=True)
    la_p.add_argument("--compute", default="count")
    _add_time_args(la_p)
    _add_json(la_p)
    la_p.set_defaults(func=cmd_logs_aggregate)

    # --- apm ---
    apm_p = sub.add_parser("apm")
    apm_sub = apm_p.add_subparsers(dest="action")

    as_p = apm_sub.add_parser("search", parents=[common])
    as_p.add_argument("--query", "-q", required=True)
    as_p.add_argument("--limit", type=int, default=25)
    _add_time_args(as_p)
    _add_json(as_p)
    as_p.set_defaults(func=cmd_apm_search)

    at_p = apm_sub.add_parser("trace", parents=[common], help="Fetch all spans for a trace ID and show grouped summary")
    at_p.add_argument("trace_id", metavar="TRACE_ID")
    at_p.add_argument("--stats", action="store_true", help="Show min/max/avg duration per group")
    _add_time_args(at_p)
    _add_json(at_p)
    at_p.set_defaults(func=cmd_apm_trace)

    aer_p = apm_sub.add_parser("endpoint-report", parents=[common], help="Sample recent traces for an endpoint and show internal call stats")
    aer_p.add_argument("endpoint", nargs="?", default=None, metavar="RESOURCE")
    aer_p.add_argument("--endpoints", nargs="+", metavar="RESOURCE", help="Multiple endpoints (alternative to positional)")
    aer_p.add_argument("--service", "-s", default=None, help="Filter by service name")
    aer_p.add_argument("--sample", type=int, default=5, help="Number of traces to sample (default: 5)")
    aer_p.add_argument("--html", action="store_true", help="Output self-contained HTML report")
    aer_p.add_argument("--ai", action="store_true", help="Output compact AI-friendly markdown to ~/.claude/tmp/, print path")
    aer_p.add_argument("--out", default=None, metavar="PATH", help="Write output to file (default: stdout)")
    _add_time_args(aer_p)
    _add_json(aer_p)
    aer_p.set_defaults(func=cmd_apm_endpoint_report)

    aa_p = apm_sub.add_parser("aggregate", parents=[common])
    aa_p.add_argument("--query", "-q", required=True)
    aa_p.add_argument("--group-by", required=True)
    aa_p.add_argument("--compute", default="count")
    _add_time_args(aa_p)
    _add_json(aa_p)
    aa_p.set_defaults(func=cmd_apm_aggregate)

    # --- from-url ---
    fu_p = sub.add_parser("from-url", parents=[common])
    fu_p.add_argument("url")
    fu_p.set_defaults(func=cmd_from_url)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(2)

    try:
        rc = args.func(args)
        _print_rate_limit(_CLIENT.last_rate_limit if _CLIENT else None, args.show_limit)
        sys.exit(rc)
    except DatadogError as e:
        _print_rate_limit(_CLIENT.last_rate_limit if _CLIENT else None, args.show_limit)
        print(f"Error: {e}", file=sys.stderr)
        if e.body:
            print(f"Response: {e.body[:500]}", file=sys.stderr)
        sys.exit(1)
