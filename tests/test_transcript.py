"""Transcript loading: both JSONL dialects, damage tolerance, discovery.

The parser's contract is forgiveness — a corrupt line is counted, never
fatal — because transcripts are evidence gathered from the wild, not files
grantsmith controls.
"""

from __future__ import annotations

import pytest

from grantsmith.errors import TranscriptError
from grantsmith.transcript import collect_files, load_transcripts

from conftest import agent_event, write_jsonl


def test_agent_cli_event_yields_tool_call(tmp_path):
    write_jsonl(
        tmp_path / "t.jsonl",
        [agent_event("Bash", {"command": "git status"}, session="sess-9",
                     timestamp="2026-07-02T08:00:00.000Z")],
    )
    calls, stats = load_transcripts([str(tmp_path / "t.jsonl")])
    assert len(calls) == 1
    assert calls[0].tool == "Bash"
    assert calls[0].input == {"command": "git status"}
    assert calls[0].session == "sess-9"
    assert calls[0].timestamp == "2026-07-02T08:00:00.000Z"
    assert stats.tool_calls == 1


def test_generic_tool_log_shape_is_accepted(tmp_path):
    write_jsonl(
        tmp_path / "t.jsonl",
        [{"tool": "Read", "input": {"file_path": "src/app.py"}, "session": "g1"}],
    )
    calls, _ = load_transcripts([str(tmp_path / "t.jsonl")])
    assert calls[0].tool == "Read"
    assert calls[0].session == "g1"


def test_multiple_blocks_parsed_and_non_tool_lines_ignored(tmp_path):
    event = agent_event("Bash", {"command": "ls"})
    event["message"]["content"].append(
        {"type": "tool_use", "id": "toolu_2", "name": "Grep", "input": {"pattern": "x"}}
    )
    write_jsonl(
        tmp_path / "t.jsonl",
        [
            {"type": "user", "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "plain text"}},
            event,
        ],
    )
    calls, stats = load_transcripts([str(tmp_path / "t.jsonl")])
    assert [c.tool for c in calls] == ["Bash", "Grep"]
    assert stats.malformed_lines == 0


def test_malformed_lines_counted_and_skipped_blank_lines_free(tmp_path):
    write_jsonl(
        tmp_path / "t.jsonl",
        [agent_event("Bash", {"command": "ls"})],
        raw_lines=["{not json", '"a bare string"', "[1, 2, 3]", "", ""],
    )
    calls, stats = load_transcripts([str(tmp_path / "t.jsonl")])
    assert len(calls) == 1  # damage never hides the good line
    assert stats.malformed_lines == 3
    assert stats.lines == 4  # blanks are not counted as lines at all


def test_directory_discovery_is_recursive_sorted_and_deduped(tmp_path):
    (tmp_path / "sub").mkdir()
    a = write_jsonl(tmp_path / "a.jsonl", [agent_event("Bash", {"command": "ls"})])
    b = write_jsonl(tmp_path / "sub" / "b.jsonl", [agent_event("Bash", {"command": "ls"})])
    (tmp_path / "notes.txt").write_text("not a transcript")
    files = collect_files([str(tmp_path), str(a), str(b)])
    assert [f.name for f in files] == ["a.jsonl", "b.jsonl"]


def test_missing_path_raises_transcript_error(tmp_path):
    with pytest.raises(TranscriptError):
        collect_files([str(tmp_path / "nope.jsonl")])


def test_default_session_is_the_file_stem_and_stats_track_span(tmp_path):
    write_jsonl(
        tmp_path / "mysession.jsonl",
        [
            {"tool": "Grep", "input": {}, "timestamp": "2026-07-03T09:00:00.000Z"},
            {"tool": "Grep", "input": {}, "timestamp": "2026-07-01T09:00:00.000Z"},
            {"tool": "Grep", "input": {}, "timestamp": "2026-07-05T09:00:00.000Z"},
        ],
    )
    calls, stats = load_transcripts([str(tmp_path / "mysession.jsonl")])
    assert calls[0].session == "mysession"
    assert stats.sessions == {"mysession"}
    assert stats.first_timestamp.startswith("2026-07-01")
    assert stats.last_timestamp.startswith("2026-07-05")


def test_non_dict_tool_input_becomes_empty_dict(tmp_path):
    event = agent_event("Bash", {"command": "ls"})
    event["message"]["content"][0]["input"] = "not a dict"
    write_jsonl(tmp_path / "t.jsonl", [event])
    calls, _ = load_transcripts([str(tmp_path / "t.jsonl")])
    assert calls[0].input == {}
