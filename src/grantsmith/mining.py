"""The rule miner: from a pile of invocations to a ranked candidate list.

The mining policy, in one breath: **generalize only when generalizing is
free.** Concretely:

- An exact rule (``Bash(git status)``) needs ``min_count`` repeats.
- A prefix rule (``Bash(git commit:*)``) additionally needs at least two
  *distinct* variants under the stem, and passes the **risk gate**: what
  the prefix can *reach* (via :func:`grantsmith.risk.prefix_reach`) must be
  no riskier than the mildest command actually observed under it. That is
  why ``git commit -m "…"`` × 14 becomes ``Bash(git commit:*)`` while
  ``git status`` × 34 next to ``git push`` × 6 never becomes ``Bash(git:*)``
  — the prefix would reach ``git push``, which the evidence for ``git
  status`` does not justify.
- Stems are tried deepest-first (``npm run`` before ``npm``); accepted
  rules mark their evidence covered so broader stems only see the residue.
- If one variant dominates a stem (≥ 90 % of its uses), the exact rule for
  that variant is proposed instead — evidence says you run *that command*,
  not "anything starting with these words".
- File-tool paths generalize to directory patterns (``Read(src/**)``);
  nested accepted patterns are merged upward so the report never proposes
  both ``src/**`` and ``src/utils/**``. Patterns whose evidence includes a
  credential-looking path are escalated, never laundered.

Invocations already covered by the user's existing allowlist are counted
and set aside first, so re-running after adopting rules converges to
"nothing left to propose".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set

from .model import Candidate, Invocation
from .normalize import FILE_TOOLS
from .risk import assess_rule, path_sensitivity, prefix_reach, tier_index
from .rules import Rule, rule_covers
from .shellparse import stem_chain

__all__ = ["DOMINANCE", "MiningResult", "mine"]

DOMINANCE = 0.9  # one variant owning >= 90% of a stem blocks the prefix


@dataclass
class MiningResult:
    candidates: List[Candidate] = field(default_factory=list)
    total_invocations: int = 0
    bash_segments: int = 0
    already_allowed: int = 0


def _build_candidate(
    rule: Rule, invs: Sequence[Invocation], note: str = ""
) -> Candidate:
    texts = Counter(inv.match_text or inv.tool for inv in invs)
    example, _n = sorted(texts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    assessment = assess_rule(rule)
    return Candidate(
        rule=rule,
        tier=assessment.tier,
        reasons=assessment.reasons,
        count=len(invs),
        sessions=len({inv.session for inv in invs}),
        variants=len(texts),
        example=example,
        last_seen=max((inv.timestamp for inv in invs), default=""),
        note=note,
    )


# ---------------------------------------------------------------------------
# Bash
# ---------------------------------------------------------------------------


def _mine_bash(
    invs: Sequence[Invocation], min_count: int, out: List[Candidate]
) -> None:
    # Group by env-stripped exact text; remember one invocation per group
    # for its tokens (identical text implies identical tokens).
    exact_groups: Dict[str, List[Invocation]] = defaultdict(list)
    for inv in invs:
        exact_groups[inv.match_text].append(inv)

    # Cache each variant's own risk tier — the gate compares against these.
    variant_tier: Dict[str, int] = {
        text: tier_index(assess_rule(Rule(tool="Bash", specifier=text)).tier)
        for text in exact_groups
    }

    # Map every stem (all depths) to the exact texts beneath it.
    stem_exacts: Dict[str, Set[str]] = defaultdict(set)
    for text, group in exact_groups.items():
        tokens = group[0].tokens
        if not tokens:
            continue  # unparseable segments can still earn exact rules below
        for stem in stem_chain(tokens):
            stem_exacts[stem].add(text)

    def group_count(texts: Iterable[str]) -> int:
        return sum(len(exact_groups[t]) for t in texts)

    ordered_stems = sorted(
        stem_exacts,
        key=lambda s: (-len(s.split(" ")), -group_count(stem_exacts[s]), s),
    )

    covered: Set[str] = set()
    dominant_of: Dict[str, str] = {}
    for stem in ordered_stems:
        uncovered = sorted(t for t in stem_exacts[stem] if t not in covered)
        if len(uncovered) < 2:
            continue
        total = group_count(uncovered)
        if total < min_count:
            continue
        # Risk gate: the prefix's reach must not exceed the mildest variant.
        reach = tier_index(prefix_reach(stem).tier)
        if reach > min(variant_tier[t] for t in uncovered):
            continue
        top_text = max(uncovered, key=lambda t: (len(exact_groups[t]), t))
        if len(exact_groups[top_text]) >= DOMINANCE * total:
            dominant_of.setdefault(top_text, stem)
            continue
        rule = Rule(tool="Bash", specifier=stem, prefix=True)
        group = [inv for t in uncovered for inv in exact_groups[t]]
        note = "covers {} variants".format(len(uncovered))
        out.append(_build_candidate(rule, group, note))
        covered.update(uncovered)

    for text in sorted(exact_groups):
        if text in covered:
            continue
        group = exact_groups[text]
        if len(group) < min_count:
            continue
        note = ""
        if text in dominant_of:
            note = "dominant variant of `{}`".format(dominant_of[text])
        out.append(_build_candidate(Rule(tool="Bash", specifier=text), group, note))


# ---------------------------------------------------------------------------
# File tools (Read / Edit / Write / NotebookEdit)
# ---------------------------------------------------------------------------


def _dir_patterns(path: str) -> List[str]:
    """Directory glob patterns for *path*, deepest directory first."""
    parts = [p for p in path.split("/") if p]
    absolute = path.startswith("/")
    if len(parts) < 2:
        return []
    patterns = []
    for depth in range(len(parts) - 1, 0, -1):
        prefix = "/".join(parts[:depth])
        patterns.append(("//" if absolute else "") + prefix + "/**")
    return patterns


def _pattern_subsumes(broad: str, narrow: str) -> bool:
    """True when directory pattern *broad* covers everything *narrow* does."""
    return narrow != broad and narrow.startswith(broad[: -len("**")])


def _mine_file_tool(
    tool: str, invs: Sequence[Invocation], min_count: int, out: List[Candidate]
) -> None:
    path_groups: Dict[str, List[Invocation]] = defaultdict(list)
    for inv in invs:
        path_groups[inv.text].append(inv)

    pattern_paths: Dict[str, Set[str]] = defaultdict(set)
    for path in path_groups:
        for pattern in _dir_patterns(path):
            pattern_paths[pattern].add(path)

    def group_count(paths: Iterable[str]) -> int:
        return sum(len(path_groups[p]) for p in paths)

    ordered = sorted(
        pattern_paths,
        key=lambda pat: (-pat.count("/"), -group_count(pattern_paths[pat]), pat),
    )
    accepted: List[str] = []
    covered: Set[str] = set()
    for pattern in ordered:
        uncovered = sorted(p for p in pattern_paths[pattern] if p not in covered)
        if len(uncovered) < 2:
            continue
        if group_count(uncovered) < min_count:
            continue
        accepted.append(pattern)
        covered.update(uncovered)

    # Merge nested accepted patterns upward: proposing both `src/**` and
    # `src/utils/**` would be redundant — the broad one wins and absorbs
    # the narrow one's evidence.
    final = [
        pat
        for pat in accepted
        if not any(_pattern_subsumes(other, pat) for other in accepted)
    ]
    for pattern in sorted(final):
        paths = sorted(p for p in covered if pattern in _dir_patterns(p))
        group = [inv for p in paths for inv in path_groups[p]]
        note = "covers {} files".format(len(paths))
        candidate = _build_candidate(Rule(tool=tool, specifier=pattern), group, note)
        # Never launder a credential read under a benign directory rule.
        for p in paths:
            marker = path_sensitivity(p)
            if marker:
                escalated = candidate.reasons + (
                    "evidence includes `{}`: likely credentials or secrets".format(p),
                )
                if tier_index("high") > tier_index(candidate.tier):
                    candidate.tier = "high"
                candidate.reasons = escalated
                break
        out.append(candidate)

    for path in sorted(path_groups):
        if path in covered:
            continue
        group = path_groups[path]
        if len(group) < min_count:
            continue
        out.append(_build_candidate(Rule(tool=tool, specifier=path), group))


# ---------------------------------------------------------------------------
# WebFetch + entry point
# ---------------------------------------------------------------------------


def _mine_webfetch(
    invs: Sequence[Invocation], min_count: int, out: List[Candidate]
) -> None:
    by_domain: Dict[str, List[Invocation]] = defaultdict(list)
    for inv in invs:
        by_domain[inv.text].append(inv)
    for domain in sorted(by_domain):
        group = by_domain[domain]
        if len(group) < min_count:
            continue
        rule = Rule(tool="WebFetch", specifier="domain:" + domain)
        out.append(_build_candidate(rule, group))


def mine(
    invocations: Sequence[Invocation],
    existing_rules: Sequence[Rule] = (),
    min_count: int = 3,
) -> MiningResult:
    """Mine *invocations* into ranked candidates, honoring existing rules."""
    result = MiningResult(total_invocations=len(invocations))
    result.bash_segments = sum(1 for inv in invocations if inv.tool == "Bash")

    remaining: List[Invocation] = []
    for inv in invocations:
        if any(rule_covers(rule, inv) for rule in existing_rules):
            result.already_allowed += 1
        else:
            remaining.append(inv)

    by_tool: Dict[str, List[Invocation]] = defaultdict(list)
    for inv in remaining:
        by_tool[inv.tool].append(inv)

    candidates: List[Candidate] = []
    for tool in sorted(by_tool):
        invs = by_tool[tool]
        if tool == "Bash":
            _mine_bash(invs, min_count, candidates)
        elif tool in FILE_TOOLS:
            _mine_file_tool(tool, invs, min_count, candidates)
        elif tool == "WebFetch":
            _mine_webfetch(invs, min_count, candidates)
        else:
            # Tool-wide rules: Glob, Grep, WebSearch, TodoWrite, mcp__*, ...
            if len(invs) >= min_count:
                candidates.append(_build_candidate(Rule(tool=tool), invs))

    candidates.sort(key=Candidate.sort_key)
    result.candidates = candidates
    return result
