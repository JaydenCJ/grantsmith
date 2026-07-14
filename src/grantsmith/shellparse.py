"""Quote-aware shell command segmentation and tokenization.

Permission rules apply to individual commands, but agents love compound
lines (``cd pkg && npm test``, ``grep -r foo | head``). Before anything can
be mined or risk-scored, a raw ``Bash`` command string has to be split into
the simple commands ("segments") the shell would actually run.

This module does that with a small character scanner that understands
single quotes, double quotes, backslash escapes, ``$(...)`` substitution,
and backticks — so ``echo "a && b"`` is one segment, not two. It is
deliberately conservative: anything it cannot parse is flagged rather than
guessed at, and the risk model treats "unparseable" as high risk.

No shell is ever invoked; this is pure string analysis.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

__all__ = [
    "Segment",
    "parse_command",
    "split_segments",
    "stem_chain",
    "stem_tokens",
]

# Flags attached to a parsed segment. The risk model keys off these.
FLAG_SUBSTITUTION = "substitution"  # contains $(...) or `...`
FLAG_REDIRECT = "redirect"  # contains an unquoted > or >> or <
FLAG_UNPARSED = "unparsed"  # shlex could not tokenize the segment

_ENV_ASSIGN_RE = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|[^\s'\"]*)*\s+"
)


@dataclass(frozen=True)
class Segment:
    """One simple command extracted from a (possibly compound) shell line."""

    raw: str  # the segment exactly as written, trimmed
    stripped: str  # raw with leading VAR=value assignments removed
    tokens: Optional[Tuple[str, ...]]  # shlex tokens of `stripped`, or None
    flags: frozenset = field(default_factory=frozenset)

    @property
    def head(self) -> str:
        """The command name (first token), or '' when unparseable/empty."""
        return self.tokens[0] if self.tokens else ""


def split_segments(command: str) -> List[str]:
    """Split a shell line into simple-command strings.

    Splits on the control operators ``&&``, ``||``, ``;``, ``|``, ``&`` and
    newlines, but only outside quotes, backslash escapes, ``$(...)`` and
    backticks. An ``&`` that is part of a redirection (``2>&1``, ``>&2``,
    ``&>log``) stays with its command. Empty segments (e.g. from a trailing
    ``&``) are dropped.
    """
    segments: List[str] = []
    buf: List[str] = []
    in_single = False
    in_double = False
    escaped = False
    paren_depth = 0  # depth inside $( ... )
    in_backtick = False
    i = 0
    n = len(command)

    def flush() -> None:
        text = "".join(buf).strip()
        buf.clear()
        if text:
            segments.append(text)

    while i < n:
        ch = command[i]
        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\" and not in_single:
            buf.append(ch)
            escaped = True
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                in_single = False
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if ch == "`":
            in_backtick = not in_backtick
            buf.append(ch)
            i += 1
            continue
        if ch == "$" and i + 1 < n and command[i + 1] == "(":
            paren_depth += 1
            buf.append("$(")
            i += 2
            continue
        if ch == ")" and paren_depth > 0:
            paren_depth -= 1
            buf.append(ch)
            i += 1
            continue
        at_top = not in_double and not in_backtick and paren_depth == 0
        if at_top:
            if ch in "&|" and i + 1 < n and command[i + 1] == ch:
                flush()
                i += 2
                continue
            if ch == "&" and (
                (buf and buf[-1] in "<>") or command[i + 1 : i + 2] == ">"
            ):
                # redirection ampersand (`2>&1`, `>&2`, `&>log`), not a
                # control operator — losing it would mint a junk segment
                buf.append(ch)
                i += 1
                continue
            if ch in ";|&\n":
                flush()
                i += 1
                continue
        buf.append(ch)
        i += 1
    flush()
    return segments


def _scan_flags(raw: str) -> frozenset:
    """Detect substitution and redirection outside single/double quotes."""
    flags = set()
    in_single = False
    in_double = False
    escaped = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if escaped:
            escaped = False
        elif ch == "\\" and not in_single:
            escaped = True
        elif in_single:
            if ch == "'":
                in_single = False
        elif ch == "'":
            in_single = True
        elif ch == '"':
            in_double = not in_double
        elif not in_double:
            if ch == "`" or (ch == "$" and raw[i + 1 : i + 2] == "("):
                flags.add(FLAG_SUBSTITUTION)
            elif ch in "<>":
                flags.add(FLAG_REDIRECT)
        elif ch == "`" or (ch == "$" and raw[i + 1 : i + 2] == "("):
            # substitution runs even inside double quotes
            flags.add(FLAG_SUBSTITUTION)
        i += 1
    return frozenset(flags)


def _strip_env_assignments(raw: str) -> str:
    """Remove leading ``NAME=value`` assignments (``FOO=1 npm test``)."""
    out = raw
    while True:
        m = _ENV_ASSIGN_RE.match(out)
        if not m:
            return out
        out = out[m.end() :]


def parse_command(command: str) -> List[Segment]:
    """Split *command* and parse each segment into a :class:`Segment`."""
    result: List[Segment] = []
    for raw in split_segments(command):
        stripped = _strip_env_assignments(raw).strip() or raw
        flags = set(_scan_flags(raw))
        tokens: Optional[Tuple[str, ...]] = None
        try:
            parts = shlex.split(stripped, posix=True)
            if parts:
                tokens = tuple(parts)
            else:
                flags.add(FLAG_UNPARSED)
        except ValueError:
            flags.add(FLAG_UNPARSED)
        result.append(
            Segment(raw=raw, stripped=stripped, tokens=tokens, flags=frozenset(flags))
        )
    return result


# ---------------------------------------------------------------------------
# Command stems
# ---------------------------------------------------------------------------

#: Commands whose first argument is a meaningful subcommand (``git status``).
SUBCOMMAND_HEADS = frozenset(
    {
        "apt",
        "apt-get",
        "aws",
        "brew",
        "bundle",
        "cargo",
        "conda",
        "docker",
        "gcloud",
        "gem",
        "gh",
        "git",
        "go",
        "helm",
        "just",
        "kubectl",
        "mix",
        "npm",
        "pip",
        "pip3",
        "pnpm",
        "poetry",
        "rails",
        "systemctl",
        "terraform",
        "uv",
        "yarn",
    }
)

#: (head, subcommand) pairs where a third token is still part of the stem
#: (``npm run build``, ``docker compose up``).
NESTED_SUBCOMMANDS = frozenset(
    {
        ("aws", "s3"),
        ("docker", "compose"),
        ("gh", "issue"),
        ("gh", "pr"),
        ("gh", "repo"),
        ("gh", "run"),
        ("git", "remote"),
        ("git", "stash"),
        ("npm", "run"),
        ("pnpm", "run"),
        ("yarn", "run"),
    }
)

_PYTHONS = frozenset({"python", "python3"})


def stem_tokens(tokens: Tuple[str, ...]) -> Tuple[str, ...]:
    """Return the deepest command stem for *tokens*.

    The stem is the part of a command that names *what* runs, as opposed to
    its arguments: ``git commit`` for ``git commit -m "fix"``, and
    ``python -m pytest`` for ``python -m pytest tests/``. Options
    (``-x`` / ``--x``) never extend a stem.
    """
    if not tokens:
        return ()
    head = tokens[0]
    stem = [head]
    if head in _PYTHONS and len(tokens) >= 3 and tokens[1] == "-m":
        return (head, "-m", tokens[2])
    if head in SUBCOMMAND_HEADS and len(tokens) >= 2 and not tokens[1].startswith("-"):
        stem.append(tokens[1])
        if (head, tokens[1]) in NESTED_SUBCOMMANDS and len(tokens) >= 3 and not tokens[
            2
        ].startswith("-"):
            stem.append(tokens[2])
    return tuple(stem)


def stem_chain(tokens: Tuple[str, ...]) -> List[str]:
    """Every stem prefix for *tokens*, shallowest first.

    ``npm run build --watch`` yields ``["npm", "npm run", "npm run build"]``
    so the miner can weigh a broad rule against narrower ones.
    """
    deepest = stem_tokens(tokens)
    if not deepest:
        return []
    if deepest[1:2] == ("-m",):  # "python -m mod" has no useful shallower stem
        return [deepest[0], " ".join(deepest)]
    return [" ".join(deepest[: i + 1]) for i in range(len(deepest))]
