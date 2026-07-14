"""Report rendering: the text report, JSON output, and explain cards.

Rendering is pure string building, so these tests assert on real output
fragments — the same strings a user reads to decide what to adopt.
"""

from __future__ import annotations

import json

from grantsmith.mining import mine
from grantsmith.pipeline import ScanReport
from grantsmith.report import render_explain, render_json, render_scan
from grantsmith.risk import assess_rule
from grantsmith.rules import parse_rule
from grantsmith.transcript import TranscriptStats

from conftest import repeat_bash


def make_report(invs, min_count=3):
    result = mine(invs, min_count=min_count)
    stats = TranscriptStats(
        files=1,
        lines=len(invs),
        tool_calls=len(invs),
        sessions={i.session for i in invs},
        first_timestamp="2026-07-01T10:00:00.000Z",
        last_timestamp="2026-07-01T10:59:00.000Z",
    )
    return ScanReport(stats=stats, result=result, min_count=min_count)


def test_scan_header_cites_the_evidence():
    report = make_report(repeat_bash("git status", 5))
    text = render_scan(report, top=20, max_risk="medium")
    assert "mined 5 tool calls from 1 transcript (1 session" in text
    assert "2026-07-01 → 2026-07-01" in text
    assert "candidate rules" in text


def test_scan_table_ranks_and_annotates():
    report = make_report(repeat_bash("git status", 6) + repeat_bash("npm test", 4))
    text = render_scan(report, top=20, max_risk="medium")
    lines = text.splitlines()
    status_line = next(l for l in lines if "Bash(git status)" in l)
    assert "safe" in status_line and "6" in status_line
    assert lines.index(status_line) < lines.index(
        next(l for l in lines if "Bash(npm test)" in l)
    )


def test_held_back_section_lists_reasons():
    report = make_report(repeat_bash("git push", 4))
    text = render_scan(report, top=20, max_risk="medium")
    assert "held back above --max-risk medium" in text
    assert "Bash(git push)" in text
    assert "publishes commits to a remote" in text


def test_empty_result_message_and_top_truncation_hint():
    report = make_report(repeat_bash("git status", 1))
    text = render_scan(report, top=20, max_risk="medium")
    assert "no candidate rules within --max-risk medium" in text

    invs = []
    for cmd in ("git status", "git diff", "npm test", "pytest -q"):
        invs += repeat_bash(cmd, 3)
    report = make_report(invs)
    text = render_scan(report, top=2, max_risk="medium")
    assert "… 2 more within --max-risk medium" in text


def test_held_back_counts_use_singular_forms():
    # "1 rule, 1 call" — never "1 rules" / "1 calls".
    report = make_report(repeat_bash("git push", 1), min_count=1)
    text = render_scan(report, top=20, max_risk="medium")
    assert "(1 rule, 1 call):" in text


def test_damage_and_unparsed_settings_surface_in_the_header():
    report = make_report(repeat_bash("git status", 3))
    report.stats.malformed_lines = 7
    report.unparsed_settings = ["not a rule!!"]
    text = render_scan(report, top=20, max_risk="medium")
    assert "malformed lines" in text and "7" in text
    assert "could not be parsed" in text
    assert "not a rule!!" in text


def test_json_output_is_valid_complete_and_respects_top():
    report = make_report(repeat_bash("git status", 5) + repeat_bash("git push", 3))
    payload = json.loads(render_json(report, top=20, max_risk="medium"))
    assert payload["stats"]["tool_calls"] == 8
    assert payload["max_risk"] == "medium"
    assert [c["rule"] for c in payload["candidates"]] == ["Bash(git status)"]
    held = payload["held_back"][0]
    assert held["rule"] == "Bash(git push)"
    assert held["tier"] == "high"
    assert held["count"] == 3
    assert isinstance(held["reasons"], list) and held["reasons"]

    invs = []
    for cmd in ("git status", "git diff", "npm test", "pytest -q", "mypy src"):
        invs += repeat_bash(cmd, 3)
    limited = json.loads(render_json(make_report(invs), top=2, max_risk="medium"))
    assert len(limited["candidates"]) == 2


def test_explain_card_lists_tier_and_reasons():
    rule = parse_rule("Bash(git:*)")
    text = render_explain(str(rule), assess_rule(rule))
    assert text.startswith("rule: Bash(git:*)\nrisk: high\n")
    assert "  - " in text


def test_long_rules_are_clipped_with_ellipsis():
    long_cmd = "curl -s " + "https://api.example.test/" + "x" * 60
    report = make_report(repeat_bash(long_cmd, 3))
    text = render_scan(report, top=20, max_risk="critical")
    assert "…" in text
