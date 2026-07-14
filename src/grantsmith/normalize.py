"""Turning raw tool calls into matchable :class:`~grantsmith.model.Invocation`s.

This is where tool-specific knowledge about *inputs* lives:

- ``Bash`` commands are split into simple-command segments (one invocation
  each), because permission rules apply per command, not per line.
- File tools contribute their path.
- ``WebFetch`` contributes the URL's host, lowercased, without a port or a
  leading ``www.`` — the granularity ``domain:`` rules use.
- Everything else (``Glob``, ``Grep``, MCP tools, …) is tool-wide usage.

Calls whose input is missing the relevant field are dropped here rather
than guessed at; the miner only ever sees well-formed evidence.
"""

from __future__ import annotations

from typing import List
from urllib.parse import urlparse

from .model import Invocation, ToolCall
from .shellparse import parse_command

__all__ = ["FILE_TOOLS", "normalize_call", "normalize_calls"]

FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit"})
_PATH_KEYS = ("file_path", "path", "notebook_path")


def _domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[len("www.") :]
    return host


def normalize_call(call: ToolCall) -> List[Invocation]:
    """Expand one transcript tool call into zero or more invocations."""
    if call.tool == "Bash":
        command = call.input.get("command")
        if not isinstance(command, str) or not command.strip():
            return []
        out = []
        for seg in parse_command(command):
            out.append(
                Invocation(
                    tool="Bash",
                    text=seg.raw,
                    stripped=seg.stripped,
                    tokens=seg.tokens or (),
                    flags=seg.flags,
                    session=call.session,
                    timestamp=call.timestamp,
                )
            )
        return out

    if call.tool in FILE_TOOLS:
        for key in _PATH_KEYS:
            path = call.input.get(key)
            if isinstance(path, str) and path:
                return [
                    Invocation(
                        tool=call.tool,
                        text=path,
                        session=call.session,
                        timestamp=call.timestamp,
                    )
                ]
        return []

    if call.tool == "WebFetch":
        url = call.input.get("url")
        if not isinstance(url, str):
            return []
        domain = _domain_of(url)
        if not domain:
            return []
        return [
            Invocation(
                tool="WebFetch",
                text=domain,
                session=call.session,
                timestamp=call.timestamp,
            )
        ]

    # Tool-wide usage: Glob, Grep, WebSearch, TodoWrite, Task, mcp__*, ...
    return [
        Invocation(
            tool=call.tool, text="", session=call.session, timestamp=call.timestamp
        )
    ]


def normalize_calls(calls: List[ToolCall]) -> List[Invocation]:
    """Normalize a whole transcript's calls, preserving order."""
    out: List[Invocation] = []
    for call in calls:
        out.extend(normalize_call(call))
    return out
