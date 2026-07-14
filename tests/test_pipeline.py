"""End-to-end pipeline: transcripts on disk in, ranked report out."""

from __future__ import annotations

from grantsmith.pipeline import run_scan, split_by_risk

from conftest import agent_event, write_jsonl


def test_run_scan_end_to_end(transcript_dir):
    directory, _file = transcript_dir
    report = run_scan([str(directory)], min_count=3)
    rules = [str(c.rule) for c in report.candidates]
    assert "Bash(git status)" in rules
    assert "Bash(git push)" in rules  # proposed, but tiered high
    assert "Read(src/app.py)" in rules
    assert "Grep" in rules
    assert report.stats.sessions == {"s1", "s2"}
    assert report.result.already_allowed == 0


def test_run_scan_honors_settings(transcript_dir, tmp_path):
    directory, _file = transcript_dir
    settings = tmp_path / "settings.json"
    settings.write_text('{"permissions": {"allow": ["Bash(git status)", "Grep"]}}')
    report = run_scan([str(directory)], settings_path=str(settings), min_count=3)
    rules = [str(c.rule) for c in report.candidates]
    assert "Bash(git status)" not in rules
    assert "Grep" not in rules
    assert report.result.already_allowed == 7  # 4 git status + 3 Grep


def test_split_by_risk_partitions_on_the_budget(transcript_dir):
    directory, _file = transcript_dir
    report = run_scan([str(directory)], min_count=3)
    within, beyond = split_by_risk(report.candidates, "medium")
    assert all(c.tier in ("safe", "low", "medium") for c in within)
    assert [str(c.rule) for c in beyond] == ["Bash(git push)"]
    all_within, none = split_by_risk(report.candidates, "critical")
    assert none == []
    assert len(all_within) == len(report.candidates)


def test_min_count_threshold_flows_through(tmp_path):
    write_jsonl(
        tmp_path / "t.jsonl",
        [agent_event("Bash", {"command": "git status"})] * 2,
    )
    assert run_scan([str(tmp_path)], min_count=3).candidates == []
    assert [str(c.rule) for c in run_scan([str(tmp_path)], min_count=2).candidates] == [
        "Bash(git status)"
    ]
