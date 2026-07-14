"""Shared helpers for the grantsmith test suite.

Everything here is deterministic and offline: transcripts are written to
pytest tmp dirs, sessions and timestamps are fixed strings, and no test
ever shells out or touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from grantsmith.model import Invocation, ToolCall
from grantsmith.normalize import normalize_call


def bash_invocations(
    command: str, session: str = "s1", timestamp: str = "2026-07-01T10:00:00.000Z"
) -> List[Invocation]:
    """Normalize one Bash command into invocations (splitting segments)."""
    call = ToolCall(
        tool="Bash",
        input={"command": command},
        session=session,
        timestamp=timestamp,
        source="test",
    )
    return normalize_call(call)


def repeat_bash(command: str, times: int, session: str = "s1") -> List[Invocation]:
    """*times* copies of the invocations for one Bash command."""
    out: List[Invocation] = []
    for i in range(times):
        out.extend(
            bash_invocations(
                command,
                session=session,
                timestamp="2026-07-01T10:{:02d}:00.000Z".format(i % 60),
            )
        )
    return out


def tool_invocation(
    tool: str,
    text: str = "",
    session: str = "s1",
    timestamp: str = "2026-07-01T10:00:00.000Z",
) -> Invocation:
    return Invocation(tool=tool, text=text, session=session, timestamp=timestamp)


def agent_event(
    tool: str,
    tool_input: Dict[str, Any],
    session: str = "abc-123",
    timestamp: str = "2026-07-01T10:00:00.000Z",
) -> Dict[str, Any]:
    """One agent-CLI style transcript line containing a tool_use block."""
    return {
        "type": "assistant",
        "sessionId": session,
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": tool, "input": tool_input}],
        },
    }


def write_jsonl(path: Path, objects: List[Any], raw_lines: Optional[List[str]] = None) -> Path:
    """Write JSONL where *objects* are dumped and *raw_lines* appended as-is."""
    lines = [json.dumps(o) for o in objects]
    if raw_lines:
        lines.extend(raw_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def transcript_dir(tmp_path: Path) -> Tuple[Path, Path]:
    """A directory with one realistic transcript file inside it."""
    events = (
        [agent_event("Bash", {"command": "git status"}, session="s1")] * 4
        + [agent_event("Bash", {"command": "git push"}, session="s1")] * 3
        + [agent_event("Bash", {"command": "npm test"}, session="s2")] * 3
        + [agent_event("Read", {"file_path": "src/app.py"}, session="s2")] * 3
        + [agent_event("Grep", {"pattern": "def "}, session="s2")] * 3
    )
    file = write_jsonl(tmp_path / "session.jsonl", events)
    return tmp_path, file
