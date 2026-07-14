"""Shared dataclasses passed between the pipeline stages.

Kept dependency-free (only stdlib dataclasses) so every other module can
import from here without cycles: transcripts produce :class:`ToolCall`,
normalization turns those into :class:`Invocation`, mining aggregates
invocations into :class:`Candidate` rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

__all__ = ["Candidate", "Invocation", "ToolCall"]


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation as it appeared in a transcript."""

    tool: str
    input: Dict[str, Any]
    session: str
    timestamp: str  # ISO-8601 string, possibly ""
    source: str  # transcript file the call came from


@dataclass(frozen=True)
class Invocation:
    """A normalized, matchable unit of tool usage.

    A single ``Bash`` call can yield several invocations (one per command
    segment); file tools yield one invocation per path; ``WebFetch`` yields
    one per domain. ``text`` is what permission specifiers match against.
    """

    tool: str
    text: str  # segment / path / domain; "" for tool-wide usage
    stripped: str = ""  # bash only: text with env assignments removed
    tokens: Tuple[str, ...] = ()  # bash only: shlex tokens of `stripped`
    flags: frozenset = field(default_factory=frozenset)
    session: str = ""
    timestamp: str = ""

    @property
    def match_text(self) -> str:
        """The string permission specifiers are matched against."""
        return self.stripped or self.text


@dataclass
class Candidate:
    """A proposed allowlist rule plus the evidence that earned it."""

    rule: "Rule"  # noqa: F821 - grantsmith.rules.Rule (avoid import cycle)
    tier: str
    reasons: Tuple[str, ...]
    count: int  # invocations this rule would have allowed
    sessions: int  # distinct sessions those invocations span
    variants: int  # distinct invocation texts covered
    example: str  # most frequent covered invocation text
    last_seen: str  # newest timestamp among covered invocations
    note: str = ""  # human hint, e.g. "dominant variant of `npm run`"

    def sort_key(self) -> Tuple[int, int, str]:
        from .risk import tier_index  # local import to avoid a cycle

        return (-self.count, tier_index(self.tier), str(self.rule))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule": str(self.rule),
            "tier": self.tier,
            "reasons": list(self.reasons),
            "count": self.count,
            "sessions": self.sessions,
            "variants": self.variants,
            "example": self.example,
            "last_seen": self.last_seen,
            "note": self.note,
        }
