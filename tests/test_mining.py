"""The miner: evidence thresholds, the risk gate, dominance, subsumption.

The central promise under test: **generalize only when generalizing is
free** — a prefix rule whose reach is riskier than its evidence must never
be proposed, no matter how many prompts it would save.
"""

from __future__ import annotations

from grantsmith.mining import mine
from grantsmith.rules import parse_rule

from conftest import repeat_bash, tool_invocation


def rules_of(result):
    return [str(c.rule) for c in result.candidates]


def by_rule(result, text):
    return next(c for c in result.candidates if str(c.rule) == text)


def test_exact_rule_requires_min_count_and_totals_are_accounted():
    result = mine(repeat_bash("git status", 2), min_count=3)
    assert rules_of(result) == []
    assert result.total_invocations == 2
    assert result.bash_segments == 2
    result = mine(repeat_bash("git status", 3), min_count=3)
    assert rules_of(result) == ["Bash(git status)"]


def test_prefix_needs_two_distinct_variants_then_covers_them_all():
    # Ten identical commands are evidence for an exact rule, not a prefix.
    invs = repeat_bash("git commit -m fix", 10)
    assert rules_of(mine(invs, min_count=3)) == ["Bash(git commit -m fix)"]
    # Varying arguments under one stem are what earns a prefix.
    invs = []
    for i in range(6):
        invs += repeat_bash('git commit -m "msg {}"'.format(i), 1)
    result = mine(invs, min_count=3)
    assert rules_of(result) == ["Bash(git commit:*)"]
    c = by_rule(result, "Bash(git commit:*)")
    assert c.count == 6
    assert c.variants == 6
    assert c.note == "covers 6 variants"


def test_risk_gate_blocks_risky_reach_but_allows_mild_stems():
    # git status (safe) + git push (high) must NOT become Bash(git:*).
    invs = repeat_bash("git status", 10) + repeat_bash("git push", 5)
    result = mine(invs, min_count=3)
    assert "Bash(git:*)" not in rules_of(result)
    assert "Bash(git status)" in rules_of(result)
    assert "Bash(git push)" in rules_of(result)
    # A stem whose whole reach is mild generalizes freely.
    invs = (
        repeat_bash("git log --oneline -20", 3)
        + repeat_bash("git log --oneline -10", 2)
        + repeat_bash("git log -p src/app.py", 1)
    )
    result = mine(invs, min_count=3)
    assert rules_of(result) == ["Bash(git log:*)"]
    assert by_rule(result, "Bash(git log:*)").count == 6


def test_dominant_variant_produces_exact_rule_not_prefix():
    # 19 of 20 uses are one command: proposing the prefix would grant far
    # more than the evidence supports.
    invs = repeat_bash("pytest -q", 19) + repeat_bash("pytest tests/x.py", 1)
    result = mine(invs, min_count=3)
    assert rules_of(result) == ["Bash(pytest -q)"]
    assert by_rule(result, "Bash(pytest -q)").note == "dominant variant of `pytest`"


def test_deeper_stem_wins_over_shallower_stem():
    invs = (
        repeat_bash("npm run build", 2)
        + repeat_bash("npm run build --watch", 2)
        + repeat_bash("npm run dev", 2)
    )
    result = mine(invs, min_count=3)
    # "npm run build" (depth 3) is tried before "npm run" (depth 2).
    assert "Bash(npm run build:*)" in rules_of(result)


def test_env_prefixes_merge_and_compounds_are_mined_per_segment():
    invs = repeat_bash("npm test", 2) + repeat_bash("CI=1 npm test", 1)
    result = mine(invs, min_count=3)
    assert rules_of(result) == ["Bash(npm test)"]
    assert by_rule(result, "Bash(npm test)").count == 3

    invs = repeat_bash("git add -A && git status", 3)
    result = mine(invs, min_count=3)
    assert set(rules_of(result)) == {"Bash(git add -A)", "Bash(git status)"}
    assert result.bash_segments == 6


def test_existing_rules_absorb_evidence_and_reruns_converge():
    invs = repeat_bash("git status", 5) + repeat_bash("npm test", 4)
    result = mine(invs, existing_rules=[parse_rule("Bash(git status)")], min_count=3)
    assert result.already_allowed == 5
    assert rules_of(result) == ["Bash(npm test)"]
    # adopting everything proposed leaves nothing on the next run
    first = mine(invs, min_count=3)
    second = mine(invs, existing_rules=[c.rule for c in first.candidates], min_count=3)
    assert second.candidates == []
    assert second.already_allowed == len(invs)


def test_file_pattern_needs_two_paths_else_exact_rule():
    invs = [tool_invocation("Read", "src/app.py") for _ in range(5)]
    assert rules_of(mine(invs, min_count=3)) == ["Read(src/app.py)"]
    invs = (
        [tool_invocation("Read", "src/app.py") for _ in range(2)]
        + [tool_invocation("Read", "src/routes.py") for _ in range(2)]
    )
    result = mine(invs, min_count=3)
    assert rules_of(result) == ["Read(src/**)"]
    assert by_rule(result, "Read(src/**)").note == "covers 2 files"


def test_nested_file_patterns_merge_upward_and_absolute_paths_anchor():
    invs = (
        [tool_invocation("Read", "src/app.py") for _ in range(2)]
        + [tool_invocation("Read", "src/routes.py") for _ in range(2)]
        + [tool_invocation("Read", "src/utils/io.py") for _ in range(2)]
        + [tool_invocation("Read", "src/utils/render.py") for _ in range(2)]
    )
    result = mine(invs, min_count=3)
    # never both src/** and src/utils/**
    assert rules_of(result) == ["Read(src/**)"]
    assert by_rule(result, "Read(src/**)").count == 8

    invs = (
        [tool_invocation("Read", "/opt/data/a.csv") for _ in range(2)]
        + [tool_invocation("Read", "/opt/data/b.csv") for _ in range(2)]
    )
    assert rules_of(mine(invs, min_count=3)) == ["Read(//opt/data/**)"]


def test_sensitive_evidence_escalates_a_directory_pattern():
    invs = (
        [tool_invocation("Read", "config/app.yaml") for _ in range(2)]
        + [tool_invocation("Read", "config/.env.production") for _ in range(2)]
    )
    result = mine(invs, min_count=3)
    c = by_rule(result, "Read(config/**)")
    assert c.tier == "high"
    assert any(".env" in r for r in c.reasons)


def test_webfetch_by_domain_tool_wide_and_mcp_rules():
    invs = (
        [tool_invocation("WebFetch", "docs.example.test") for _ in range(3)]
        + [tool_invocation("WebFetch", "api.example.test")]
        + [tool_invocation("Grep") for _ in range(3)]
        + [tool_invocation("mcp__tracker__list_issues") for _ in range(4)]
        + [tool_invocation("mcp__tracker__create_issue") for _ in range(2)]
    )
    result = mine(invs, min_count=3)
    assert set(rules_of(result)) == {
        "WebFetch(domain:docs.example.test)",  # api.example.test is below threshold
        "Grep",
        "mcp__tracker__list_issues",  # create_issue is below threshold
    }


def test_ranking_and_evidence_fields():
    invs = (
        repeat_bash("git status", 5)
        + repeat_bash("npm test", 5)
        + repeat_bash("git diff", 9)
    )
    result = mine(invs, min_count=3)
    assert rules_of(result) == [
        "Bash(git diff)",  # most calls first
        "Bash(git status)",  # ties broken by tier: safe before low
        "Bash(npm test)",
    ]

    invs = repeat_bash("git status", 2, session="s1") + repeat_bash(
        "git status", 2, session="s2"
    )
    c = by_rule(mine(invs, min_count=3), "Bash(git status)")
    assert c.count == 4
    assert c.sessions == 2
    assert c.variants == 1
    assert c.example == "git status"
    assert c.last_seen.startswith("2026-07-01")


def test_unparseable_commands_can_still_earn_exact_rules():
    invs = repeat_bash("echo 'unterminated", 3)
    result = mine(invs, min_count=3)
    (c,) = result.candidates
    assert str(c.rule) == "Bash(echo 'unterminated)"
    assert c.tier == "high"  # unparseable is never presumed safe
