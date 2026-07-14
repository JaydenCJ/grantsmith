# grantsmith examples

Three synthetic-but-realistic agent session transcripts from a fictional
web project, plus a small settings file, so every command in the main
README runs against data that ships with the repository.

## Files

| File | What it is |
|---|---|
| `transcripts/session-9f2c41aa.jsonl` | Session 1 (2026-06-30): feature work — git, npm, pytest, file reads/edits |
| `transcripts/session-b81d7c33.jsonl` | Session 2 (2026-07-05): auth bugfix — includes `rm -rf node_modules`, `npm install` |
| `transcripts/session-e4a9160b.jsonl` | Session 3 (2026-07-11): pager fixes — includes compound commands and env-prefixed calls |
| `sample_settings.json` | An existing allowlist (`Bash(ls:*)`, `Grep`) to demonstrate already-allowed accounting |

Together: 229 tool calls across 3 sessions — enough repetition for the
miner to find real structure (exact rules, a `git commit:*` prefix, file
patterns, a WebFetch domain, MCP tools) and real risk (`git push`,
`rm -rf`, `curl`).

## Try it

```bash
# ranked candidates + held-back risky rules
grantsmith scan examples/transcripts

# what your current settings already cover
grantsmith scan examples/transcripts --settings examples/sample_settings.json

# adoptable snippet, conservative budget
grantsmith emit examples/transcripts --max-risk low
```

The exact expected results are pinned by `tests/test_examples.py` — if the
miner's output for these files ever changes, that test fails, so the docs
and the code cannot drift apart.

The transcripts use the agent-CLI JSONL shape (assistant events carrying
`tool_use` blocks). Real transcripts live under `~/.claude/projects/` on a
machine that uses such a CLI; point `grantsmith scan` at that directory —
or at any directory of `.jsonl` files — the same way.
