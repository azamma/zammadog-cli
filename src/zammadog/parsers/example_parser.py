"""Example log parser — a copy-me template (committed as living documentation).

A parser transforms generic ``CompactLog`` rows into a leaner, business-specific form
before rendering, then the CLI prints them via ``render_parsed`` as ``ts | trace_id | msg``.

To build your own:
  1. Copy this file to ``<yourbiz>_parser.py`` in this folder (it will be git-ignored).
  2. Implement ``parse(rows) -> rows`` — do NOT mutate inputs; use ``dataclasses.replace``.
  3. Call ``register("<yourbiz>", YourParser())`` at module level.
The module is auto-loaded on import, so ``zammadog cw ... --parser <yourbiz>`` just works.

This example does one common, framework-agnostic thing: many loggers emit
``<prefix> --- <logger> : <message>``; it keeps only the part after ``---``.
"""
from __future__ import annotations

from dataclasses import replace

from ..compact import CompactLog
from . import register

_SEP = " --- "


class ExampleParser:
    """Keeps only the text after a ``---`` separator; otherwise leaves the row untouched."""

    def parse(self, rows: list[CompactLog]) -> list[CompactLog]:
        out: list[CompactLog] = []
        for row in rows:
            msg = row.msg.split(_SEP, 1)[1] if _SEP in row.msg else row.msg
            out.append(replace(row, msg=msg.rstrip()))
        return out


register("example", ExampleParser())
