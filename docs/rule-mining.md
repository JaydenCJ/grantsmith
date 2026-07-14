# How grantsmith mines and scores rules

This document specifies the mining pipeline and the risk model precisely
enough to reproduce any number in a report by hand. Source of truth:
`src/grantsmith/mining.py` and `src/grantsmith/risk.py`; the behaviors
below are pinned by the test suite.

## 1. From transcripts to invocations

1. Every `.jsonl` file under the given paths is read line by line.
   Two shapes yield tool calls: agent-CLI assistant events with
   `message.content[].type == "tool_use"`, and generic
   `{"tool": …, "input": …}` objects. Malformed lines are counted and
   skipped — one corrupt line never hides a session.
2. Each tool call becomes zero or more **invocations**:
   - `Bash` commands are split into simple-command *segments* on `&&`,
     `||`, `;`, `|`, `&`, and newlines — but never inside single/double
     quotes, `$(...)`, or backticks, and never on the `&` of a redirection
     (`2>&1`, `>&2`, `&>log`). Each segment is one invocation.
     Leading `NAME=value` assignments are stripped for matching (the raw
     text is kept for display). Unquoted `>`/`<`, command substitution,
     and unparseable text set flags the risk model consumes.
   - `Read`/`Edit`/`Write`/`NotebookEdit` contribute their path;
     `WebFetch` contributes the URL's host (lowercased, no port, no
     leading `www.`); `Glob`, `Grep`, `WebSearch`, MCP tools, and anything
     else count as tool-wide usage.
3. Invocations covered by the `--settings` allowlist are counted as
   *already allowed* and excluded from mining, so adopting rules and
   re-scanning converges to an empty proposal list.

## 2. Candidate generation

**Exact rules.** Any invocation text repeated at least `--min-count`
times (default 3) earns an exact candidate: `Bash(git status)`,
`Read(src/app.py)`, `WebFetch(domain:docs.example.test)`,
`mcp__tracker__list_issues`, or a bare tool name for tool-wide usage.

**Bash prefix rules.** Every segment yields a chain of stems from a
subcommand grammar (`npm run build --watch` → `npm`, `npm run`,
`npm run build`; options never extend a stem). Stems are tried
deepest-first; a stem is accepted as `Bash(stem:*)` only if **all** of:

1. at least 2 distinct not-yet-covered variants exist under it;
2. their total count is ≥ `--min-count`;
3. **risk gate** — the prefix's *reach* (§3) is no riskier than the
   mildest variant observed under it;
4. **dominance** — no single variant owns ≥ 90 % of the group (if one
   does, its exact rule is proposed instead, with a note).

Accepted stems mark their variants covered, so broader stems only ever
see the residue.

**File patterns.** Paths generalize to directory globs
(`Read(src/**)`, absolute paths anchored as `Read(//opt/data/**)`) under
the same ≥ 2-distinct-paths + `--min-count` thresholds; nested accepted
patterns merge upward (never both `src/**` and `src/utils/**`), and a
pattern whose evidence includes a credential-looking path is escalated to
`high`, never laundered.

**Ranking.** Candidates sort by calls covered (descending), then tier
(safer first), then rule text — fully deterministic.

## 3. The risk model

Five tiers: `safe < low < medium < high < critical`.

**Bash segments** are scored by longest-stem lookup in a ~200-entry table
(`git push` overrides `git`), then escalators apply — escalators only
ever raise:

| Escalator | Effect |
|---|---|
| `rm` with recursive + force flags (any spelling) | `critical` |
| `git push` with `-f`/`--force` | `critical` |
| `bash`/`sh`/`zsh`/… with `-c` | `critical` |
| `find` with `-delete`/`-exec`/`-execdir`/`-ok` | `high` |
| command substitution `$(...)`/backticks | at least `medium` |
| unquoted redirection `>` `<` | at least `low` |
| segment that cannot be parsed | `high` |
| unknown command | `medium` (honest uncertainty) |

**Prefix reach.** `Bash(stem:*)` is scored as the stem itself widened by
every table entry the prefix can complete into: `git:*` reaches
`git push`, so it is `high` no matter how benign the observed usage was.
The full rule assessment also adds a floor of `low` — any arguments are
allowed, after all. The miner's risk gate (§2) uses reach *without* that
floor, so `git log:*` (reach `safe`) can still generalize `safe` evidence.

**Other tools.** `Read`/`Glob`/`Grep` are `safe`; `Edit`/`Write` are
`medium`; match-everything patterns, `..` escapes, and credential-looking
paths (`.env*`, `.ssh`, `id_rsa`, `secrets`, …) escalate. Scoped
`WebFetch(domain:…)` is `medium` (fetched content can steer the agent);
unscoped `WebFetch` is `high`. MCP tools use a verb heuristic (`get_`,
`list_`, `search_`… → `low`, verify with the server) and default to
`medium`; a server-wide `mcp__server` rule is flagged as such.

Run `grantsmith explain "RULE"` to see the model's full verdict for any
rule, or `--fail-above TIER` to use it as an exit-code gate in review
scripts.
