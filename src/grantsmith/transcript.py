"""Reading tool calls out of session transcript files (JSONL).

Two line shapes are understood, and both can be mixed in one file:

1. **Agent-CLI session logs** — each line is an event object; assistant
   events carry a ``message.content`` list whose ``tool_use`` blocks name
   the tool and its input. Session id and timestamp ride on the event.
2. **Generic tool logs** — one object per line with top-level ``tool``
   (or ``name``) and ``input`` keys, plus optional ``session`` /
   ``timestamp``.

Parsing is forgiving by design: a transcript is evidence, not a contract.
Malformed lines are counted and skipped, never fatal — one corrupt line
must not hide a week of history. Only a missing/unreadable *file* raises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

from .errors import TranscriptError
from .model import ToolCall

__all__ = ["TranscriptStats", "collect_files", "load_transcripts", "parse_line"]


@dataclass
class TranscriptStats:
    """What was read, so reports can cite their evidence honestly."""

    files: int = 0
    lines: int = 0
    malformed_lines: int = 0
    tool_calls: int = 0
    sessions: Set[str] = field(default_factory=set)
    first_timestamp: str = ""
    last_timestamp: str = ""

    def observe_timestamp(self, ts: str) -> None:
        if not ts:
            return
        if not self.first_timestamp or ts < self.first_timestamp:
            self.first_timestamp = ts
        if ts > self.last_timestamp:
            self.last_timestamp = ts


def collect_files(paths: Iterable[str]) -> List[Path]:
    """Expand files and directories into a sorted list of ``.jsonl`` files."""
    found: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found.extend(sorted(p.rglob("*.jsonl")))
        elif p.is_file():
            found.append(p)
        else:
            raise TranscriptError("transcript path not found: {}".format(p))
    # de-duplicate while keeping deterministic order
    seen: Set[Path] = set()
    unique: List[Path] = []
    for p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def _tool_use_blocks(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract ``tool_use`` blocks from an agent-CLI event, if any."""
    message = obj.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    blocks = []
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and isinstance(block.get("name"), str)
        ):
            blocks.append(block)
    return blocks


def parse_line(obj: Dict[str, Any], default_session: str, source: str) -> List[ToolCall]:
    """Turn one decoded JSONL object into zero or more :class:`ToolCall`."""
    session = obj.get("sessionId") or obj.get("session") or default_session
    timestamp = obj.get("timestamp") or ""
    if not isinstance(session, str):
        session = default_session
    if not isinstance(timestamp, str):
        timestamp = ""

    calls: List[ToolCall] = []
    for block in _tool_use_blocks(obj):
        tool_input = block.get("input")
        calls.append(
            ToolCall(
                tool=block["name"],
                input=tool_input if isinstance(tool_input, dict) else {},
                session=session,
                timestamp=timestamp,
                source=source,
            )
        )
    if calls:
        return calls

    # Generic shape: {"tool": "...", "input": {...}}
    tool = obj.get("tool") or obj.get("name")
    if isinstance(tool, str) and tool and "input" in obj:
        tool_input = obj.get("input")
        return [
            ToolCall(
                tool=tool,
                input=tool_input if isinstance(tool_input, dict) else {},
                session=session,
                timestamp=timestamp,
                source=source,
            )
        ]
    return []


def load_transcripts(paths: Iterable[str]) -> Tuple[List[ToolCall], TranscriptStats]:
    """Read every transcript under *paths*; returns calls and stats."""
    stats = TranscriptStats()
    calls: List[ToolCall] = []
    for path in collect_files(paths):
        stats.files += 1
        default_session = path.stem
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise TranscriptError("cannot read {}: {}".format(path, exc))
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            stats.lines += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats.malformed_lines += 1
                continue
            if not isinstance(obj, dict):
                stats.malformed_lines += 1
                continue
            for call in parse_line(obj, default_session, str(path)):
                calls.append(call)
                stats.tool_calls += 1
                stats.sessions.add(call.session)
                stats.observe_timestamp(call.timestamp)
    return calls, stats
