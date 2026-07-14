"""Permission rule strings: parsing, formatting, and coverage matching.

Rules use the agent-CLI allowlist syntax:

- ``ToolName`` — allow every use of a tool (``Grep``).
- ``ToolName(specifier)`` — allow a subset (``Bash(git status)``,
  ``Read(src/**)``, ``WebFetch(domain:example.test)``).
- ``Bash(prefix:*)`` — allow any command starting with *prefix* at a token
  boundary (``Bash(npm run:*)`` matches ``npm run build`` but not
  ``npm runaway``).
- ``mcp__server`` / ``mcp__server__tool`` — MCP server-wide or per-tool.

`rule_covers` answers "would this rule have allowed that invocation?" — it
drives both the "already allowed by your settings" accounting and the
subsumption checks inside the miner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .errors import RuleSyntaxError
from .model import Invocation

__all__ = ["Rule", "parse_rule", "rule_covers"]

_RULE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\((.*)\)$", re.DOTALL)
_BARE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit"})


@dataclass(frozen=True)
class Rule:
    """A parsed permission rule."""

    tool: str
    specifier: Optional[str] = None  # None means tool-wide
    prefix: bool = False  # Bash(x:*) prefix form

    def __str__(self) -> str:
        if self.specifier is None:
            return self.tool
        spec = self.specifier + ":*" if self.prefix else self.specifier
        return "{}({})".format(self.tool, spec)

    @property
    def is_mcp(self) -> bool:
        return self.tool.startswith("mcp__")

    @property
    def mcp_server_wide(self) -> bool:
        """True for a bare ``mcp__server`` rule (no ``__tool`` part)."""
        return self.is_mcp and self.specifier is None and self.tool.count("__") == 1


def parse_rule(text: str) -> Rule:
    """Parse a rule string; raise :class:`RuleSyntaxError` when malformed."""
    text = text.strip()
    if not text:
        raise RuleSyntaxError("empty rule")
    m = _RULE_RE.match(text)
    if m:
        tool, spec = m.group(1), m.group(2)
        if spec == "":
            raise RuleSyntaxError(
                "empty specifier in {!r}; use a bare tool name to allow everything".format(
                    text
                )
            )
        if tool == "Bash" and spec.endswith(":*"):
            base = spec[:-2].strip()
            if not base:
                raise RuleSyntaxError("empty prefix in {!r}".format(text))
            return Rule(tool=tool, specifier=base, prefix=True)
        return Rule(tool=tool, specifier=spec)
    if _BARE_RE.match(text):
        return Rule(tool=text)
    raise RuleSyntaxError("cannot parse rule {!r}".format(text))


# ---------------------------------------------------------------------------
# Coverage matching
# ---------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> "re.Pattern[str]":
    """Translate a ``**``-aware glob into a compiled regex.

    ``**`` crosses directory separators, ``*`` and ``?`` do not. A leading
    ``//`` anchors the pattern at the filesystem root (absolute paths).
    """
    if pattern.startswith("//"):
        pattern = pattern[1:]  # '//etc/**' -> '/etc/**'
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 3] == "**/":
                out.append(r"(?:[^/]+/)*")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(r".*")
                i += 2
                continue
            out.append(r"[^/]*")
        elif ch == "?":
            out.append(r"[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def _bash_covers(rule: Rule, inv: Invocation) -> bool:
    spec = rule.specifier or ""
    target = inv.match_text
    if rule.prefix:
        return target == spec or target.startswith(spec + " ")
    return target == spec or inv.text == spec


def _webfetch_covers(spec: str, domain: str) -> bool:
    if spec.startswith("domain:"):
        wanted = spec[len("domain:") :].strip().lower()
        got = domain.lower()
        return got == wanted or got.endswith("." + wanted)
    return spec == domain


def rule_covers(rule: Rule, inv: Invocation) -> bool:
    """Would *rule* have allowed *inv* without a prompt?"""
    if rule.is_mcp:
        if rule.tool == inv.tool:
            return True
        return rule.mcp_server_wide and inv.tool.startswith(rule.tool + "__")
    if rule.tool != inv.tool:
        return False
    if rule.specifier is None:
        return True
    if rule.tool == "Bash":
        return _bash_covers(rule, inv)
    if rule.tool == "WebFetch":
        return _webfetch_covers(rule.specifier, inv.text)
    if rule.tool in _FILE_TOOLS:
        return bool(_glob_to_regex(rule.specifier).match(inv.text))
    return rule.specifier == inv.text
