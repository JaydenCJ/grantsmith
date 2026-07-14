"""The ``grantsmith`` command-line interface.

Three subcommands, one shared philosophy — print, never write:

- ``scan``    — mine transcripts, show ranked candidates + held-back risks.
- ``emit``    — print adoptable rules as a settings snippet (or a fully
  merged settings file with ``--merge``), filtered by ``--max-risk``.
- ``explain`` — score any rule string against the risk model.

grantsmith never modifies your settings file; adopting a rule is always an
explicit copy/paste or shell redirect done by you.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .errors import GrantsmithError
from .pipeline import run_scan, split_by_risk
from .report import render_explain, render_json, render_scan
from .risk import TIERS, assess_rule, tier_index
from .rules import parse_rule
from .settings import emit_snippet, merge_settings, render_settings

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grantsmith",
        description=(
            "Mine agent session transcripts and propose ranked permission "
            "allowlist rules with risk annotations."
        ),
    )
    parser.add_argument(
        "--version", action="version", version="grantsmith {}".format(__version__)
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "paths",
            nargs="+",
            metavar="PATH",
            help="transcript .jsonl files or directories to scan recursively",
        )
        p.add_argument(
            "--settings",
            metavar="FILE",
            help="existing settings.json; already-allowed calls are not re-proposed",
        )
        p.add_argument(
            "--min-count",
            type=int,
            default=3,
            metavar="N",
            help="evidence threshold: a rule needs N covered calls (default 3)",
        )
        p.add_argument(
            "--max-risk",
            choices=TIERS,
            default="medium",
            metavar="TIER",
            help="risk budget: safe|low|medium|high|critical (default medium)",
        )

    p_scan = sub.add_parser("scan", help="rank candidate rules from transcripts")
    add_common(p_scan)
    p_scan.add_argument(
        "--top", type=int, default=20, metavar="N", help="show at most N rules (default 20)"
    )
    p_scan.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )

    p_emit = sub.add_parser(
        "emit", help="print adoptable rules as a settings snippet"
    )
    add_common(p_emit)
    p_emit.add_argument(
        "--merge",
        action="store_true",
        help="print the full --settings file with new rules appended",
    )

    p_explain = sub.add_parser("explain", help="score one rule against the risk model")
    p_explain.add_argument("rule", metavar="RULE", help='e.g. "Bash(git push:*)"')
    p_explain.add_argument(
        "--fail-above",
        choices=TIERS,
        metavar="TIER",
        help="exit 1 if the rule scores worse than TIER (for CI gates)",
    )
    p_explain.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def _cmd_scan(args: argparse.Namespace) -> int:
    report = run_scan(args.paths, settings_path=args.settings, min_count=args.min_count)
    if args.json:
        sys.stdout.write(render_json(report, top=args.top, max_risk=args.max_risk))
    else:
        sys.stdout.write(render_scan(report, top=args.top, max_risk=args.max_risk))
    return 0


def _cmd_emit(args: argparse.Namespace) -> int:
    report = run_scan(args.paths, settings_path=args.settings, min_count=args.min_count)
    within, beyond = split_by_risk(report.candidates, args.max_risk)
    rules = [c.rule for c in within]
    if args.merge:
        if not args.settings:
            raise GrantsmithError("--merge requires --settings FILE")
        merged = merge_settings(args.settings, rules)
        sys.stdout.write(render_settings(merged))
    else:
        sys.stdout.write(render_settings(emit_snippet(rules)))
    if beyond:
        sys.stderr.write(
            "grantsmith: held back {} rule{} above --max-risk {}; "
            "run `grantsmith scan` to review\n".format(
                len(beyond), "s" if len(beyond) != 1 else "", args.max_risk
            )
        )
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    rule = parse_rule(args.rule)
    assessment = assess_rule(rule)
    if args.json:
        payload = {
            "rule": str(rule),
            "tier": assessment.tier,
            "reasons": list(assessment.reasons),
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(render_explain(str(rule), assessment))
    if args.fail_above and tier_index(assessment.tier) > tier_index(args.fail_above):
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        if args.command == "scan":
            return _cmd_scan(args)
        if args.command == "emit":
            return _cmd_emit(args)
        if args.command == "explain":
            return _cmd_explain(args)
    except GrantsmithError as exc:
        sys.stderr.write("grantsmith: {}\n".format(exc))
        return 1
    return 2  # pragma: no cover — argparse restricts commands


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
