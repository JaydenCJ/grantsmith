"""The CLI surface: subcommands, flags, exit codes, and error handling.

Driven through ``grantsmith.cli.main`` in-process with captured stdio —
the exact code path the console script runs, minus process spawning.
"""

from __future__ import annotations

import json

import pytest

from grantsmith import __version__
from grantsmith.cli import main


def run_cli(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_version_flag_and_bare_invocation(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "grantsmith " + __version__
    code, out, _ = run_cli(capsys)
    assert code == 2  # no command: print help, signal usage error
    assert "scan" in out and "emit" in out and "explain" in out


def test_scan_text_and_json_reports(capsys, transcript_dir):
    directory, _ = transcript_dir
    code, out, _ = run_cli(capsys, "scan", str(directory))
    assert code == 0
    assert "Bash(git status)" in out
    assert "held back above --max-risk medium" in out
    assert "Bash(git push)" in out

    code, out, _ = run_cli(capsys, "scan", str(directory), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["stats"]["files"] == 1
    assert any(c["rule"] == "Bash(git status)" for c in payload["candidates"])


def test_scan_missing_path_exits_1_with_message(capsys, tmp_path):
    code, _, err = run_cli(capsys, "scan", str(tmp_path / "missing.jsonl"))
    assert code == 1
    assert err.startswith("grantsmith:")
    assert "not found" in err


def test_emit_snippet_respects_the_risk_budget(capsys, transcript_dir):
    directory, _ = transcript_dir
    code, out, err = run_cli(capsys, "emit", str(directory))
    assert code == 0
    allow = json.loads(out)["permissions"]["allow"]
    assert "Bash(git status)" in allow
    assert "Bash(git push)" not in allow  # high > default medium budget
    assert "held back 1 rule above" in err  # singular — no "1 rules"

    code, out, err = run_cli(capsys, "emit", str(directory), "--max-risk", "high")
    assert code == 0
    assert "Bash(git push)" in json.loads(out)["permissions"]["allow"]
    assert err == ""


def test_emit_merge_needs_and_uses_settings(capsys, transcript_dir, tmp_path):
    directory, _ = transcript_dir
    code, _, err = run_cli(capsys, "emit", str(directory), "--merge")
    assert code == 1
    assert "--merge requires --settings" in err

    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus", "permissions": {"allow": ["Glob"]}}')
    code, out, _ = run_cli(
        capsys, "emit", str(directory), "--settings", str(settings), "--merge"
    )
    assert code == 0
    merged = json.loads(out)
    assert merged["model"] == "opus"
    assert merged["permissions"]["allow"][0] == "Glob"
    assert "Bash(git status)" in merged["permissions"]["allow"]


def test_settings_and_min_count_flags_shape_the_scan(capsys, transcript_dir, tmp_path):
    directory, _ = transcript_dir
    settings = tmp_path / "settings.json"
    settings.write_text('{"permissions": {"allow": ["Grep"]}}')
    code, out, _ = run_cli(capsys, "scan", str(directory), "--settings", str(settings))
    assert code == 0
    header = next(l for l in out.splitlines() if "already allowed" in l)
    assert "3" in header

    _, strict_out, _ = run_cli(capsys, "scan", str(directory), "--min-count", "5")
    assert "Bash(git status)" not in strict_out
    _, lax_out, _ = run_cli(capsys, "scan", str(directory), "--min-count", "1")
    assert "Bash(git status)" in lax_out


def test_explain_text_and_json_outputs(capsys):
    code, out, _ = run_cli(capsys, "explain", "Bash(npm run:*)")
    assert code == 0
    assert out.startswith("rule: Bash(npm run:*)\nrisk: low\n")

    code, out, _ = run_cli(capsys, "explain", "Read(~/.ssh/**)", "--json")
    assert code == 0
    assert json.loads(out) == {
        "rule": "Read(~/.ssh/**)",
        "tier": "high",
        "reasons": [
            "reads file contents only",
            "touches `.ssh`: likely credentials or secrets",
        ],
    }


def test_explain_fail_above_gates_ci(capsys):
    code, out, _ = run_cli(capsys, "explain", "Bash(git status)", "--fail-above", "safe")
    assert code == 0
    code, out, _ = run_cli(capsys, "explain", "Bash(git push)", "--fail-above", "medium")
    assert code == 1
    assert "risk: high" in out  # the card still prints before the gate trips


def test_usage_errors(capsys, transcript_dir):
    code, _, err = run_cli(capsys, "explain", "???")
    assert code == 1
    assert "cannot parse rule" in err
    directory, _ = transcript_dir
    with pytest.raises(SystemExit) as exc:
        main(["scan", str(directory), "--max-risk", "extreme"])
    assert exc.value.code == 2
