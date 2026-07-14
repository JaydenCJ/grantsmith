"""The bundled examples must keep producing the output the README shows.

These tests pin the shipped sample transcripts to the documented results,
so docs, demo SVG, and code can never drift apart silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from grantsmith.cli import main
from grantsmith.pipeline import run_scan

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_sample_transcripts_exist_and_parse_cleanly():
    report = run_scan([str(EXAMPLES / "transcripts")])
    assert report.stats.files == 3
    assert len(report.stats.sessions) == 3
    assert report.stats.malformed_lines == 0
    assert report.stats.tool_calls == 229


def test_sample_scan_proposes_and_holds_back_the_documented_rules():
    report = run_scan([str(EXAMPLES / "transcripts")])
    rules = [str(c.rule) for c in report.candidates]
    # the README's top-of-report examples
    assert rules[0] == "Bash(git status)"
    assert "Bash(npm run:*)" in rules
    assert "Bash(git commit:*)" in rules
    assert "Read(src/**)" in rules
    assert "WebFetch(domain:docs.example.test)" in rules
    # the ones that must never be proposed
    assert "Bash(git:*)" not in rules
    assert "Bash(npm:*)" not in rules
    # and the risky evidence stays visible but tiered honestly
    tiers = {str(c.rule): c.tier for c in report.candidates}
    assert tiers["Bash(git push)"] == "high"
    assert tiers["Bash(rm -rf node_modules)"] == "critical"


def test_sample_settings_suppress_covered_rules(capsys):
    code = main(
        [
            "scan",
            str(EXAMPLES / "transcripts"),
            "--settings",
            str(EXAMPLES / "sample_settings.json"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "already allowed" in out
    assert "Bash(ls -la)" not in out  # covered by Bash(ls:*)
    assert "Grep " not in out.split("NOTE", 1)[1]  # covered by Grep


def test_sample_emit_snippet_is_stable_json(capsys):
    code = main(["emit", str(EXAMPLES / "transcripts"), "--max-risk", "low"])
    out = capsys.readouterr().out
    assert code == 0
    snippet = json.loads(out)
    allow = snippet["permissions"]["allow"]
    assert "Bash(git status)" in allow
    assert all("git push" not in rule for rule in allow)
