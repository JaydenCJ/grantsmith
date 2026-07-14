# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-13

### Added

- Transcript reader for agent-CLI session logs (JSONL `tool_use` events)
  and generic `{"tool": …, "input": …}` tool logs, with per-line damage
  tolerance: malformed lines are counted and skipped, never fatal.
- Quote-aware shell segmentation: compound `Bash` commands are split on
  `&&`, `||`, `;`, `|`, `&` and newlines — but never inside quotes,
  `$(...)`, or backticks — so rules are mined per simple command.
  Environment-variable prefixes (`CI=1 npm test`) are stripped for
  matching; substitution, redirection, and unparseable segments are
  flagged for the risk model.
- Rule miner with evidence thresholds (`--min-count`), deepest-stem-first
  greedy generalization, a 90 % dominance check, and the **risk gate**: a
  prefix rule is proposed only when its reach is no riskier than the
  mildest command observed under it (`git commit -m …` × 14 becomes
  `Bash(git commit:*)`; `git status` next to `git push` never becomes
  `Bash(git:*)`).
- Directory-pattern mining for `Read`/`Edit`/`Write` paths with upward
  merging of nested patterns and credential-path escalation; domain
  grouping for `WebFetch`; tool-wide rules for `Glob`/`Grep`/MCP tools.
- Five-tier risk model (`safe`→`critical`): a ~200-entry command table
  with longest-stem lookup, flag escalators (`rm -rf`, `git push --force`,
  `sh -c`, `find -exec`), shell-construct escalators, prefix-reach
  analysis, sensitive-path detection, and honest `medium` defaults for
  unknown commands and tools.
- Existing-allowlist awareness: `--settings` reads `permissions.allow`,
  counts already-covered calls, and re-runs converge to "nothing left to
  propose".
- `grantsmith` CLI: `scan` (ranked report with a held-back section,
  `--json`), `emit` (settings snippet or `--merge` into a full settings
  file; never writes files itself), and `explain` (risk card for any rule,
  `--fail-above` exit-code gate for CI).
- Three bundled sample transcripts (229 tool calls across 3 sessions) that
  the README quickstart, demo SVG, and `tests/test_examples.py` all pin.
- 92 pytest tests and `scripts/smoke.sh` (prints `SMOKE OK`), all offline
  and deterministic.

### Notes

- The repository ships no CI workflow; verification is local — `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.

[0.1.0]: https://github.com/JaydenCJ/grantsmith/releases/tag/v0.1.0
