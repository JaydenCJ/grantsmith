"""Normalization: tool calls become matchable invocations.

Per-tool input knowledge lives here — command splitting for Bash, path
extraction for file tools, domain extraction for WebFetch — and calls with
missing fields must vanish instead of producing junk evidence.
"""

from __future__ import annotations

from grantsmith.model import ToolCall
from grantsmith.normalize import normalize_call, normalize_calls


def call(tool, tool_input):
    return ToolCall(tool=tool, input=tool_input, session="s", timestamp="", source="t")


def test_bash_single_command_one_invocation_with_tokens():
    (inv,) = normalize_call(call("Bash", {"command": "git status"}))
    assert inv.tool == "Bash"
    assert inv.text == "git status"
    assert inv.tokens == ("git", "status")


def test_bash_compound_command_yields_one_invocation_per_segment():
    invs = normalize_call(call("Bash", {"command": "git add -A && git commit -m x"}))
    assert [i.text for i in invs] == ["git add -A", "git commit -m x"]


def test_bash_env_prefix_populates_stripped_and_match_text():
    (inv,) = normalize_call(call("Bash", {"command": "CI=1 npm test"}))
    assert inv.text == "CI=1 npm test"
    assert inv.stripped == "npm test"
    assert inv.match_text == "npm test"


def test_calls_missing_their_relevant_field_are_dropped():
    assert normalize_call(call("Bash", {})) == []
    assert normalize_call(call("Bash", {"command": "   "})) == []
    assert normalize_call(call("Bash", {"command": 42})) == []
    assert normalize_call(call("Read", {"pattern": "x"})) == []
    assert normalize_call(call("WebFetch", {"url": "not a url"})) == []
    assert normalize_call(call("WebFetch", {})) == []


def test_file_tools_extract_their_path():
    (r,) = normalize_call(call("Read", {"file_path": "src/app.py"}))
    (e,) = normalize_call(call("Edit", {"file_path": "src/app.py"}))
    (n,) = normalize_call(call("NotebookEdit", {"notebook_path": "nb/analysis.ipynb"}))
    assert (r.tool, r.text) == ("Read", "src/app.py")
    assert e.tool == "Edit"
    assert n.text == "nb/analysis.ipynb"


def test_webfetch_extracts_lowercase_domain_without_www_or_port():
    (inv,) = normalize_call(
        call("WebFetch", {"url": "https://WWW.Docs.Example.TEST:8443/a/b?q=1"})
    )
    assert inv.text == "docs.example.test"


def test_tool_wide_invocations_and_order_preservation():
    (g,) = normalize_call(call("Grep", {"pattern": "def "}))
    (m,) = normalize_call(call("mcp__tracker__list_issues", {"state": "open"}))
    assert (g.tool, g.text) == ("Grep", "")
    assert (m.tool, m.text) == ("mcp__tracker__list_issues", "")
    invs = normalize_calls(
        [call("Bash", {"command": "a; b"}), call("Read", {"file_path": "x.py"})]
    )
    assert [i.text for i in invs] == ["a", "b", "x.py"]
