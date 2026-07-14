"""End-to-end orchestration: transcripts in, ranked candidates out.

The pipeline is a straight line — load, normalize, mine — with the user's
existing allowlist threaded through so already-granted invocations are
accounted for rather than re-proposed. Both the CLI and library users call
:func:`run_scan`; everything it computes is on the returned
:class:`ScanReport`, so rendering (text or JSON) needs no further logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .mining import MiningResult, mine
from .model import Candidate
from .normalize import normalize_calls
from .risk import tier_index
from .rules import Rule
from .settings import load_allowlist
from .transcript import TranscriptStats, load_transcripts

__all__ = ["ScanReport", "run_scan", "split_by_risk"]


@dataclass
class ScanReport:
    stats: TranscriptStats
    result: MiningResult
    existing_rules: List[Rule] = field(default_factory=list)
    unparsed_settings: List[str] = field(default_factory=list)
    min_count: int = 3

    @property
    def candidates(self) -> List[Candidate]:
        return self.result.candidates


def run_scan(
    paths: Sequence[str],
    settings_path: Optional[str] = None,
    min_count: int = 3,
) -> ScanReport:
    """Scan *paths* (files or directories of ``.jsonl`` transcripts)."""
    existing_rules: List[Rule] = []
    unparsed: List[str] = []
    if settings_path:
        existing_rules, unparsed = load_allowlist(settings_path)

    calls, stats = load_transcripts(paths)
    invocations = normalize_calls(calls)
    result = mine(invocations, existing_rules=existing_rules, min_count=min_count)
    return ScanReport(
        stats=stats,
        result=result,
        existing_rules=existing_rules,
        unparsed_settings=unparsed,
        min_count=min_count,
    )


def split_by_risk(
    candidates: Sequence[Candidate], max_risk: str
) -> "tuple[List[Candidate], List[Candidate]]":
    """Partition candidates into (within budget, held back)."""
    limit = tier_index(max_risk)
    within = [c for c in candidates if tier_index(c.tier) <= limit]
    beyond = [c for c in candidates if tier_index(c.tier) > limit]
    return within, beyond
