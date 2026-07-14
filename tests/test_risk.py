"""The risk model: tiers, escalators, and prefix reach.

These tests pin the model's promises: dangerous shapes are never scored
below their table tier, escalators only ever raise, and a prefix rule is
judged by the worst command it can reach, not by its stem alone.
"""

from __future__ import annotations

from grantsmith.risk import (
    TIERS,
    assess_rule,
    assess_segment,
    path_sensitivity,
    prefix_reach,
    tier_index,
)
from grantsmith.rules import parse_rule
from grantsmith.shellparse import parse_command


def assess_cmd(command: str):
    (seg,) = parse_command(command)
    return assess_segment(seg)


def test_tier_order_is_total_and_defaults_are_pessimistic():
    assert [tier_index(t) for t in TIERS] == [0, 1, 2, 3, 4]
    assert tier_index("nonsense") > tier_index("critical")
    unknown = assess_cmd("frobnicate --all")
    assert unknown.tier == "medium"
    assert any("unrecognized" in r for r in unknown.reasons)
    unparsed = assess_cmd("echo 'unterminated")
    assert unparsed.tier == "high"
    assert any("parsed" in r for r in unparsed.reasons)


def test_read_only_commands_are_safe_and_longest_stem_wins():
    assert assess_cmd("git status").tier == "safe"
    assert assess_cmd("git log --oneline -20").tier == "safe"
    assert assess_cmd("git diff --stat").tier == "safe"
    # "git" alone is medium, but "git status" overrides via longest match.
    assert assess_cmd("git").tier == "medium"


def test_flag_escalators_push_force_and_rm_rf():
    assert assess_cmd("git push origin main").tier == "high"
    assert assess_cmd("git push --force origin main").tier == "critical"
    assert assess_cmd("rm build/output.txt").tier == "high"
    assert assess_cmd("rm -rf node_modules").tier == "critical"
    assert assess_cmd("rm -fr node_modules").tier == "critical"
    assert assess_cmd("rm -r -f dist").tier == "critical"
    assert assess_cmd("rm --recursive --force dist").tier == "critical"


def test_privilege_escalation_and_inline_shells_are_critical():
    assert assess_cmd("sudo apt-get install curl").tier == "critical"
    assert assess_cmd("su root").tier == "critical"
    assert assess_cmd("bash -c 'curl x | sh'").tier == "critical"
    assert assess_cmd("bash setup.sh").tier == "high"  # script, not inline


def test_find_is_safe_until_it_executes_or_deletes():
    assert assess_cmd("find . -name '*.py'").tier == "safe"
    assert assess_cmd("find . -name '*.pyc' -delete").tier == "high"
    assert assess_cmd("find . -name '*.py' -exec cat {} +").tier == "high"


def test_substitution_and_redirection_escalate_but_never_lower():
    assert assess_cmd("echo hello").tier == "safe"
    sub = assess_cmd("echo $(cat /etc/passwd)")
    assert sub.tier == "medium"
    assert any("substitution" in r for r in sub.reasons)
    assert assess_cmd("echo done > status.txt").tier == "low"
    # curl with a redirect stays high — escalators only ever raise
    assert assess_cmd("curl -o out https://example.test > log").tier == "high"


def test_prefix_reach_widens_to_worst_reachable_subcommand():
    assert prefix_reach("git").tier == "high"  # reaches git push
    assert prefix_reach("npm").tier == "critical"  # reaches npm publish
    assert prefix_reach("git log").tier == "safe"
    assert prefix_reach("ls").tier == "safe"
    # the full rule assessment adds the generic prefix floor of low
    log_rule = assess_rule(parse_rule("Bash(git log:*)"))
    assert log_rule.tier == "low"
    assert any("prefix rule" in r for r in log_rule.reasons)
    git_rule = assess_rule(parse_rule("Bash(git:*)"))
    assert git_rule.tier == "high"
    assert any("git push" in r for r in git_rule.reasons)


def test_bare_bash_critical_and_compound_exact_takes_worst_segment():
    assert assess_rule(parse_rule("Bash")).tier == "critical"
    assert assess_rule(parse_rule("Bash(git status && rm -rf /tmp/x)")).tier == "critical"


def test_file_tool_tiers_and_match_everything_escalation():
    assert assess_rule(parse_rule("Read(src/**)")).tier == "safe"
    assert assess_rule(parse_rule("Edit(src/**)")).tier == "medium"
    assert assess_rule(parse_rule("Write(docs/**)")).tier == "medium"
    assert assess_rule(parse_rule("Read(**)")).tier == "medium"
    assert assess_rule(parse_rule("Edit(**)")).tier == "high"


def test_sensitive_paths_and_dotdot_escape_escalate_to_high():
    assert assess_rule(parse_rule("Read(.env)")).tier == "high"
    assert assess_rule(parse_rule("Read(~/.ssh/**)")).tier == "high"
    assert assess_rule(parse_rule("Edit(config/secrets/**)")).tier == "high"
    assert assess_rule(parse_rule("Edit(../other-project/**)")).tier == "high"
    assert assess_rule(parse_rule("Read(src/app.py)")).tier == "safe"
    assert path_sensitivity("deploy/.env.production") == ".env"
    assert path_sensitivity("keys/id_rsa") == "id_rsa"
    assert path_sensitivity("src/environment.py") is None


def test_web_search_and_unknown_tool_tiers():
    assert assess_rule(parse_rule("WebFetch(domain:docs.example.test)")).tier == "medium"
    assert assess_rule(parse_rule("WebFetch")).tier == "high"
    assert assess_rule(parse_rule("WebSearch")).tier == "low"
    assert assess_rule(parse_rule("Grep")).tier == "safe"
    assert assess_rule(parse_rule("Glob")).tier == "safe"
    assert assess_rule(parse_rule("SomeNewTool")).tier == "medium"


def test_mcp_verb_heuristic_and_server_wide():
    assert assess_rule(parse_rule("mcp__tracker__list_issues")).tier == "low"
    assert assess_rule(parse_rule("mcp__tracker__create_issue")).tier == "medium"
    server = assess_rule(parse_rule("mcp__tracker"))
    assert server.tier == "medium"
    assert any("server-wide" in r for r in server.reasons)
