"""Plain-text and JSON rendering of scan results.

Pure functions from a :class:`~grantsmith.pipeline.ScanReport` to strings —
no printing, no color codes, no terminal probing — so the CLI stays a thin
wrapper and every report is byte-reproducible in tests. Output is aligned
with computed column widths and never exceeds one screen of chrome: the
numbers are the point.
"""

from __future__ import annotations

import json
from typing import List, Sequence

from .model import Candidate
from .pipeline import ScanReport, split_by_risk
from .risk import Assessment

__all__ = ["render_explain", "render_json", "render_scan"]

_RULE_COL_MAX = 44


def _clip(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _date(ts: str) -> str:
    return ts[:10] if ts else "?"


def _header(report: ScanReport) -> List[str]:
    stats = report.stats
    span = ""
    if stats.first_timestamp:
        span = ", {} → {}".format(
            _date(stats.first_timestamp), _date(stats.last_timestamp)
        )
    lines = [
        "grantsmith — mined {:,} tool calls from {} transcript{} "
        "({} session{}{})".format(
            stats.tool_calls,
            stats.files,
            "s" if stats.files != 1 else "",
            len(stats.sessions),
            "s" if len(stats.sessions) != 1 else "",
            span,
        ),
        "",
        "  tool calls seen        {:>7,}".format(stats.tool_calls),
        "  bash segments          {:>7,}".format(report.result.bash_segments),
        "  already allowed        {:>7,}".format(report.result.already_allowed),
        "  candidate rules        {:>7,}".format(len(report.candidates)),
    ]
    if stats.malformed_lines:
        lines.append(
            "  malformed lines        {:>7,}  (skipped)".format(stats.malformed_lines)
        )
    if report.unparsed_settings:
        lines.append(
            "  note: {} settings rule(s) could not be parsed and were ignored: "
            "{}".format(
                len(report.unparsed_settings), ", ".join(report.unparsed_settings)
            )
        )
    return lines


def _table(candidates: Sequence[Candidate], numbered: bool) -> List[str]:
    rule_w = max([len(_clip(str(c.rule), _RULE_COL_MAX)) for c in candidates] + [4])
    lines = []
    head = "   #  " if numbered else "      "
    lines.append(
        head
        + "{:<{w}}  {:<8}  {:>5}  {:>8}  NOTE".format("RULE", "RISK", "CALLS", "SESSIONS", w=rule_w)
    )
    for i, c in enumerate(candidates, start=1):
        prefix = "  {:>2}  ".format(i) if numbered else "      "
        lines.append(
            prefix
            + "{:<{w}}  {:<8}  {:>5}  {:>8}  {}".format(
                _clip(str(c.rule), _RULE_COL_MAX),
                c.tier,
                c.count,
                c.sessions,
                c.note,
                w=rule_w,
            ).rstrip()
        )
    return lines


def render_scan(report: ScanReport, top: int, max_risk: str) -> str:
    """The human-facing scan report."""
    lines = _header(report)
    within, beyond = split_by_risk(report.candidates, max_risk)

    if within:
        shown = within[:top]
        lines.append("")
        lines.extend(_table(shown, numbered=True))
        if len(within) > len(shown):
            lines.append(
                "      … {} more within --max-risk {} (raise --top to see them)".format(
                    len(within) - len(shown), max_risk
                )
            )
    else:
        lines.append("")
        lines.append(
            "  no candidate rules within --max-risk {} "
            "(min-count {}); try more transcripts".format(max_risk, report.min_count)
        )

    if beyond:
        calls = sum(c.count for c in beyond)
        lines.append("")
        lines.append(
            "held back above --max-risk {} ({} rule{}, {} call{}):".format(
                max_risk,
                len(beyond),
                "s" if len(beyond) != 1 else "",
                calls,
                "s" if calls != 1 else "",
            )
        )
        lines.extend(_table(beyond, numbered=False))
        for c in beyond:
            lines.append(
                "        {} — {}".format(
                    _clip(str(c.rule), _RULE_COL_MAX), "; ".join(c.reasons)
                )
            )

    if within:
        lines.append("")
        lines.append(
            "Next: `grantsmith emit …` prints these {} rule{} as a settings "
            "snippet.".format(len(within), "s" if len(within) != 1 else "")
        )
    return "\n".join(lines) + "\n"


def render_json(report: ScanReport, top: int, max_risk: str) -> str:
    """Machine-readable scan output (stable key order)."""
    within, beyond = split_by_risk(report.candidates, max_risk)
    payload = {
        "stats": {
            "files": report.stats.files,
            "lines": report.stats.lines,
            "malformed_lines": report.stats.malformed_lines,
            "tool_calls": report.stats.tool_calls,
            "sessions": len(report.stats.sessions),
            "first_timestamp": report.stats.first_timestamp,
            "last_timestamp": report.stats.last_timestamp,
            "bash_segments": report.result.bash_segments,
            "already_allowed": report.result.already_allowed,
        },
        "min_count": report.min_count,
        "max_risk": max_risk,
        "candidates": [c.as_dict() for c in within[:top]],
        "held_back": [c.as_dict() for c in beyond],
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def render_explain(rule_text: str, assessment: Assessment) -> str:
    """The `grantsmith explain` card for one rule."""
    lines = ["rule: {}".format(rule_text), "risk: {}".format(assessment.tier)]
    for reason in assessment.reasons:
        lines.append("  - {}".format(reason))
    return "\n".join(lines) + "\n"
