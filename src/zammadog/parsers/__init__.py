"""Pluggable log parsers (business adapters).

A parser is a decoupled filter that transforms generic ``CompactLog`` rows into a
business-specific compact form before rendering. The CLI selects one with
``--parser <name>``.

How it works: every ``*.py`` module dropped into this folder is auto-loaded on import.
A module defines a parser and registers it with :func:`register`. See
``example_parser.py`` for a copy-me template.

Only ``__init__.py`` and ``example_parser.py`` are committed. Your real, environment-specific
parsers (e.g. ``acme_parser.py``) live in this same folder but are git-ignored, so each
user maintains their own without leaking them upstream.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Protocol

from ..compact import CompactLog


class LogParser(Protocol):
    """Transforms a list of CompactLog rows into a business-specific compact form."""

    def parse(self, rows: list[CompactLog]) -> list[CompactLog]:
        """Return transformed rows. Must not mutate the input."""
        ...


_REGISTRY: dict[str, LogParser] = {}


def register(name: str, parser: LogParser) -> None:
    """Register a parser under a case-insensitive name."""
    _REGISTRY[name.lower()] = parser


def get_parser(name: str) -> LogParser | None:
    """Return the registered parser for ``name`` (case-insensitive), or None."""
    return _REGISTRY.get(name.lower())


def parser_names() -> list[str]:
    """Return the sorted list of registered parser names."""
    return sorted(_REGISTRY)


def render_parsed(rows: list[CompactLog]) -> str:
    """Compact one-line-per-row render: ``ts | trace_id | msg`` (for --parser output)."""
    if not rows:
        return "(no results)"
    return "\n".join(f"{r.ts or '-'} | {r.trace_id or '-'} | {r.msg}" for r in rows)


def _autoload() -> None:
    """Import every sibling module so each self-registers. A broken local parser
    must not take the whole tool down, so import errors are swallowed."""
    for mod in pkgutil.iter_modules(__path__):
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:  # pragma: no cover - depends on local modules
            pass


_autoload()
