"""Rule string parsing and coverage matching.

`rule_covers` decides both "already allowed by your settings" and prefix
subsumption inside the miner, so token-boundary and glob semantics get
edge-case coverage here.
"""

from __future__ import annotations

import pytest

from grantsmith.errors import RuleSyntaxError
from grantsmith.model import Invocation
from grantsmith.rules import Rule, parse_rule, rule_covers

from conftest import bash_invocations


def inv(tool: str, text: str) -> Invocation:
    return Invocation(tool=tool, text=text)


def test_parse_forms_and_str_round_trips():
    assert parse_rule("Grep") == Rule(tool="Grep", specifier=None, prefix=False)
    exact = parse_rule("Bash(git status)")
    assert (exact.tool, exact.specifier, exact.prefix) == ("Bash", "git status", False)
    prefix = parse_rule("Bash(npm run:*)")
    assert prefix.prefix and prefix.specifier == "npm run"
    for text in ("Grep", "Bash(git status)", "Bash(npm run:*)", "Read(src/**)"):
        assert str(parse_rule(text)) == text


def test_parse_rejects_garbage():
    for bad in ("", "two words", "Bash()", "Bash(:*)"):
        with pytest.raises(RuleSyntaxError):
            parse_rule(bad)


def test_colon_star_only_special_for_bash():
    # For non-Bash tools ":*" is part of the literal specifier.
    rule = parse_rule("Read(a:*)")
    assert not rule.prefix
    assert rule.specifier == "a:*"


def test_bash_exact_covers_that_command_and_its_env_stripped_form():
    rule = parse_rule("Bash(git status)")
    (yes,) = bash_invocations("git status")
    (no,) = bash_invocations("git status --short")
    assert rule_covers(rule, yes)
    assert not rule_covers(rule, no)
    (env_inv,) = bash_invocations("CI=1 git status")
    assert rule_covers(rule, env_inv)


def test_bash_prefix_respects_token_boundary():
    rule = parse_rule("Bash(npm run:*)")
    (build,) = bash_invocations("npm run build")
    (bare,) = bash_invocations("npm run")
    (runaway,) = bash_invocations("npm runaway")
    assert rule_covers(rule, build)
    assert rule_covers(rule, bare)
    assert not rule_covers(rule, runaway)


def test_bare_tool_rule_covers_everything_of_that_tool_only():
    rule = parse_rule("Bash")
    (anything,) = bash_invocations("sudo rm -rf /")
    assert rule_covers(rule, anything)
    assert not rule_covers(rule, inv("Read", "src/app.py"))
    assert not rule_covers(parse_rule("Edit(src/**)"), inv("Read", "src/app.py"))


def test_file_glob_semantics():
    doublestar = parse_rule("Read(src/**)")
    assert rule_covers(doublestar, inv("Read", "src/app.py"))
    assert rule_covers(doublestar, inv("Read", "src/utils/deep/io.py"))
    assert not rule_covers(doublestar, inv("Read", "tests/test_app.py"))
    assert not rule_covers(doublestar, inv("Read", "srcx/app.py"))

    single = parse_rule("Read(src/*.py)")
    assert rule_covers(single, inv("Read", "src/app.py"))
    assert not rule_covers(single, inv("Read", "src/utils/io.py"))  # no slash crossing

    mid = parse_rule("Read(src/**/conf.py)")
    assert rule_covers(mid, inv("Read", "src/conf.py"))  # ** matches zero dirs
    assert rule_covers(mid, inv("Read", "src/a/b/conf.py"))

    absolute = parse_rule("Read(//etc/**)")
    assert rule_covers(absolute, inv("Read", "/etc/hosts"))
    assert not rule_covers(absolute, inv("Read", "etc/hosts"))


def test_webfetch_domain_matches_subdomains_only_at_dot_boundary():
    rule = parse_rule("WebFetch(domain:example.test)")
    assert rule_covers(rule, inv("WebFetch", "example.test"))
    assert rule_covers(rule, inv("WebFetch", "docs.example.test"))
    assert not rule_covers(rule, inv("WebFetch", "evilexample.test"))


def test_mcp_exact_and_server_wide_rules():
    exact = parse_rule("mcp__tracker__list_issues")
    server = parse_rule("mcp__tracker")
    tool_inv = inv("mcp__tracker__list_issues", "")
    other_inv = inv("mcp__tracker__create_issue", "")
    foreign = inv("mcp__other__list_issues", "")
    assert rule_covers(exact, tool_inv)
    assert not rule_covers(exact, other_inv)
    assert server.mcp_server_wide
    assert rule_covers(server, tool_inv)
    assert rule_covers(server, other_inv)
    assert not rule_covers(server, foreign)
