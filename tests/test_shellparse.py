"""Segmentation and tokenization of shell commands.

Splitting correctness is load-bearing for everything downstream: a rule
applies per simple command, so `cd pkg && rm -rf /` must never be seen as
one harmless-looking string.
"""

from __future__ import annotations

from grantsmith.shellparse import (
    FLAG_REDIRECT,
    FLAG_SUBSTITUTION,
    FLAG_UNPARSED,
    parse_command,
    split_segments,
    stem_chain,
    stem_tokens,
)


def test_split_on_control_operators():
    assert split_segments("git status") == ["git status"]
    assert split_segments("git add -A && git commit -m x") == [
        "git add -A",
        "git commit -m x",
    ]
    assert split_segments("a; b | c || d") == ["a", "b", "c", "d"]
    assert split_segments("git status\ngit diff") == ["git status", "git diff"]
    # a trailing background & leaves no empty segment behind
    assert split_segments("npm run dev &") == ["npm run dev"]


def test_redirection_ampersands_do_not_split():
    # `2>&1` / `>&2` / `&>log` are redirections; splitting on their `&`
    # would mint a junk segment ("1") that pollutes mining and risk scoring.
    assert split_segments("npm test 2>&1") == ["npm test 2>&1"]
    assert split_segments("npm test >/dev/null 2>&1") == ["npm test >/dev/null 2>&1"]
    assert split_segments("echo err >&2") == ["echo err >&2"]
    assert split_segments("make build &> build.log") == ["make build &> build.log"]
    # a real background & between commands still splits
    assert split_segments("npm run dev & npm test") == ["npm run dev", "npm test"]


def test_quoted_operators_do_not_split():
    assert split_segments('echo "a && b"') == ['echo "a && b"']
    assert split_segments("echo 'x || y; z'") == ["echo 'x || y; z'"]


def test_operators_inside_command_substitution_do_not_split():
    # The && lives inside $( ), so the shell runs a single command.
    assert split_segments("echo $(a && b)") == ["echo $(a && b)"]


def test_substitution_flag_for_dollar_paren_and_backticks_even_in_quotes():
    (seg,) = parse_command("echo $(whoami)")
    assert FLAG_SUBSTITUTION in seg.flags
    (seg,) = parse_command("echo `date`")
    assert FLAG_SUBSTITUTION in seg.flags
    (seg,) = parse_command('echo "today is $(date)"')
    assert FLAG_SUBSTITUTION in seg.flags  # substitution runs in double quotes


def test_redirect_flag_set_only_outside_quotes():
    (seg,) = parse_command("npm test > out.log")
    assert FLAG_REDIRECT in seg.flags
    (seg,) = parse_command("echo 'a > b'")
    assert FLAG_REDIRECT not in seg.flags


def test_env_assignments_are_stripped_for_matching_but_kept_in_raw():
    (seg,) = parse_command("FOO=1 BAR=two npm test")
    assert seg.stripped == "npm test"
    assert seg.tokens == ("npm", "test")
    assert seg.raw == "FOO=1 BAR=two npm test"
    (seg,) = parse_command('MSG="hello world" ./run.sh')
    assert seg.stripped == "./run.sh"


def test_unbalanced_quote_marks_segment_unparsed_with_empty_head():
    (seg,) = parse_command("echo 'oops")
    assert FLAG_UNPARSED in seg.flags
    assert seg.tokens is None
    assert seg.head == ""
    (ok,) = parse_command("git commit -m 'x'")
    assert ok.head == "git"


def test_stems_follow_the_subcommand_grammar():
    assert stem_tokens(("git", "commit", "-m", "x")) == ("git", "commit")
    assert stem_tokens(("pytest", "tests/", "-q")) == ("pytest",)
    assert stem_tokens(("npm", "run", "build", "--watch")) == ("npm", "run", "build")
    assert stem_tokens(("docker", "compose", "up", "-d")) == ("docker", "compose", "up")
    assert stem_tokens(("python3", "-m", "pytest", "-q")) == ("python3", "-m", "pytest")
    # options never extend a stem
    assert stem_tokens(("git", "-C", "repo", "status")) == ("git",)
    assert stem_tokens(("npm", "run", "--silent", "dev")) == ("npm", "run")


def test_stem_chain_orders_shallow_to_deep():
    assert stem_chain(("npm", "run", "build")) == ["npm", "npm run", "npm run build"]
    assert stem_chain(("python3", "-m", "pytest", "-q")) == [
        "python3",
        "python3 -m pytest",
    ]
    assert stem_chain(("ls", "-la")) == ["ls"]
    assert stem_chain(()) == []
