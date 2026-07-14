"""Settings files: reading allowlists, emitting snippets, merging.

Merging must be surgical — everything the user already had, including keys
grantsmith knows nothing about, survives in place.
"""

from __future__ import annotations

import json

import pytest

from grantsmith.errors import SettingsError
from grantsmith.rules import Rule, parse_rule
from grantsmith.settings import (
    emit_snippet,
    load_allowlist,
    merge_settings,
    render_settings,
)


def write(tmp_path, data):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_load_nested_permissions_shape(tmp_path):
    path = write(tmp_path, {"permissions": {"allow": ["Bash(git status)", "Grep"]}})
    rules, unparsed = load_allowlist(path)
    assert [str(r) for r in rules] == ["Bash(git status)", "Grep"]
    assert unparsed == []


def test_load_top_level_allow_shape(tmp_path):
    path = write(tmp_path, {"allow": ["Bash(ls:*)"]})
    rules, _ = load_allowlist(path)
    assert rules == [Rule(tool="Bash", specifier="ls", prefix=True)]


def test_unparseable_rules_are_reported_not_dropped_silently(tmp_path):
    path = write(tmp_path, {"permissions": {"allow": ["Grep", "not a rule!!", 42]}})
    rules, unparsed = load_allowlist(path)
    assert [str(r) for r in rules] == ["Grep"]
    assert unparsed == ["not a rule!!"]  # the int is not a rule string at all


def test_unreadable_settings_raise_settings_error(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{broken", encoding="utf-8")
    array = tmp_path / "array.json"
    array.write_text("[1, 2]", encoding="utf-8")
    for path in (broken, array, tmp_path / "missing.json"):
        with pytest.raises(SettingsError):
            load_allowlist(str(path))


def test_emit_snippet_shape_and_rendering():
    rules = [parse_rule("Bash(git status)"), parse_rule("Grep")]
    snippet = emit_snippet(rules)
    assert snippet == {"permissions": {"allow": ["Bash(git status)", "Grep"]}}
    text = render_settings(snippet)
    assert text.endswith("\n")
    assert json.loads(text) == snippet


def test_merge_appends_dedupes_and_preserves_unrelated_keys(tmp_path):
    path = write(
        tmp_path,
        {
            "model": "opus",
            "permissions": {"allow": ["Grep"], "deny": ["Bash(sudo:*)"]},
        },
    )
    merged = merge_settings(path, [parse_rule("Grep"), parse_rule("Bash(git status)")])
    assert merged["model"] == "opus"
    assert merged["permissions"]["deny"] == ["Bash(sudo:*)"]
    assert merged["permissions"]["allow"] == ["Grep", "Bash(git status)"]


def test_merge_creates_block_when_absent_and_rejects_wrong_types(tmp_path):
    path = write(tmp_path, {"model": "opus"})
    merged = merge_settings(path, [parse_rule("Glob")])
    assert merged["permissions"]["allow"] == ["Glob"]
    bad = write(tmp_path, {"permissions": "yes please"})
    with pytest.raises(SettingsError):
        merge_settings(bad, [parse_rule("Glob")])
