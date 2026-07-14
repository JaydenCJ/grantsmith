#!/usr/bin/env bash
# Smoke test for grantsmith: scan the bundled sample transcripts, emit a
# settings snippet, merge it, and gate rules with explain — end to end.
# Self-contained: pure stdlib, no network, idempotent (works from a clean tree).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# The package has zero runtime dependencies, so running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/grantsmith-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

echo "[smoke] python: $("$PYTHON" --version 2>&1)"

# 1. scan: ranked candidates from the bundled transcripts, risky rules held back.
scan_out="$("$PYTHON" -m grantsmith scan "$ROOT/examples/transcripts")" \
  || fail "scan exited non-zero"
echo "$scan_out" | sed -n '1,8p' | sed 's/^/[scan] /'
echo "$scan_out" | grep -q "mined 229 tool calls from 3 transcripts" \
  || fail "scan header did not cite the sample evidence"
echo "$scan_out" | grep -q "Bash(git status)" || fail "scan missing Bash(git status)"
echo "$scan_out" | grep -q "Bash(git commit:\*)" || fail "scan missing the commit prefix rule"
echo "$scan_out" | grep -q "held back above --max-risk medium" \
  || fail "scan did not hold back risky rules"
echo "$scan_out" | grep -q "Bash(rm -rf node_modules)" \
  || fail "scan did not surface the rm -rf evidence"
echo "$scan_out" | grep -q "Bash(git:\*)" && fail "scan proposed the over-broad Bash(git:*)"

# 2. scan --json: machine-readable and internally consistent.
"$PYTHON" -m grantsmith scan "$ROOT/examples/transcripts" --json > "$WORKDIR/scan.json"
"$PYTHON" - "$WORKDIR/scan.json" <<'PY' || fail "scan --json failed validation"
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["stats"]["tool_calls"] == 229, payload["stats"]
assert payload["candidates"][0]["rule"] == "Bash(git status)"
assert all(c["tier"] in ("safe", "low", "medium") for c in payload["candidates"])
assert any(c["rule"] == "Bash(rm -rf node_modules)" for c in payload["held_back"])
PY

# 3. emit: a valid, budget-filtered settings snippet.
"$PYTHON" -m grantsmith emit "$ROOT/examples/transcripts" --max-risk low \
  > "$WORKDIR/snippet.json" 2> "$WORKDIR/emit.err"
grep -q "held back" "$WORKDIR/emit.err" || fail "emit did not report held-back rules"
"$PYTHON" - "$WORKDIR/snippet.json" <<'PY' || fail "emit snippet failed validation"
import json, sys
allow = json.load(open(sys.argv[1]))["permissions"]["allow"]
assert "Bash(git status)" in allow
assert not any("git push" in r or "rm -rf" in r for r in allow)
PY

# 4. emit --merge: existing settings survive, new rules append.
cp "$ROOT/examples/sample_settings.json" "$WORKDIR/settings.json"
"$PYTHON" -m grantsmith emit "$ROOT/examples/transcripts" \
  --settings "$WORKDIR/settings.json" --merge > "$WORKDIR/merged.json" 2>/dev/null
"$PYTHON" - "$WORKDIR/merged.json" <<'PY' || fail "merged settings failed validation"
import json, sys
allow = json.load(open(sys.argv[1]))["permissions"]["allow"]
assert allow[:2] == ["Bash(ls:*)", "Grep"], allow[:2]  # originals keep their order
assert "Bash(git status)" in allow
PY

# 5. re-scan with the merged settings: adopted rules stop being proposed.
rescan_out="$("$PYTHON" -m grantsmith scan "$ROOT/examples/transcripts" \
  --settings "$WORKDIR/merged.json" --max-risk critical)"
echo "$rescan_out" | grep -qE "already allowed +2[0-9][0-9]" \
  || fail "re-scan did not count adopted rules as already allowed"

# 6. explain: risk cards and the CI gate exit code.
"$PYTHON" -m grantsmith explain "Bash(git:*)" | sed 's/^/[explain] /'
"$PYTHON" -m grantsmith explain "Bash(git:*)" | grep -q "risk: high" \
  || fail "explain scored Bash(git:*) wrong"
if "$PYTHON" -m grantsmith explain "Bash(curl:*)" --fail-above medium >/dev/null; then
  fail "explain --fail-above should exit 1 for a high-risk rule"
fi

# 7. --version agrees with the package.
version_out="$("$PYTHON" -m grantsmith --version)"
pkg_version="$("$PYTHON" -c 'import grantsmith; print(grantsmith.__version__)')"
[ "$version_out" = "grantsmith $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"

echo "SMOKE OK"
