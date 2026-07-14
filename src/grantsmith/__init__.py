"""grantsmith — mine session transcripts into ranked permission allowlist rules.

Public API:

- :func:`grantsmith.pipeline.run_scan` — transcripts in, ranked report out.
- :func:`grantsmith.mining.mine` — mine pre-normalized invocations.
- :func:`grantsmith.risk.assess_rule` / :func:`grantsmith.rules.parse_rule`
  — score and parse individual rule strings.

Everything is pure standard library and fully offline: grantsmith reads
transcript files you point it at, computes, and prints. It never talks to
the network and never writes to your settings.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .errors import GrantsmithError, RuleSyntaxError, SettingsError, TranscriptError
from .mining import MiningResult, mine
from .model import Candidate, Invocation, ToolCall
from .pipeline import ScanReport, run_scan, split_by_risk
from .risk import TIERS, Assessment, assess_rule, tier_index
from .rules import Rule, parse_rule, rule_covers

__all__ = [
    "Assessment",
    "Candidate",
    "GrantsmithError",
    "Invocation",
    "MiningResult",
    "Rule",
    "RuleSyntaxError",
    "ScanReport",
    "SettingsError",
    "TIERS",
    "ToolCall",
    "TranscriptError",
    "__version__",
    "assess_rule",
    "mine",
    "parse_rule",
    "rule_covers",
    "run_scan",
    "split_by_risk",
    "tier_index",
]
