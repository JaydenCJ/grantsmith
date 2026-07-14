# Contributing to grantsmith

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Development setup

```bash
git clone https://github.com/JaydenCJ/grantsmith
cd grantsmith
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

```bash
pytest                 # 92 unit + integration tests (tests/)
bash scripts/smoke.sh  # end-to-end smoke: scan, emit, merge, explain
```

Both must pass before a pull request is reviewed; the smoke script must
print `SMOKE OK`. The whole suite runs fully offline in well under a
second and needs no API keys.

## Ground rules

- **No new runtime dependencies.** The package is standard-library only;
  that is a feature. Test-only dependencies belong in the `dev` extra.
- **Risk-model changes need receipts.** Any change to `BASH_TABLE`, an
  escalator, or the prefix gate must come with a test pinning the new
  verdict and an update to `docs/rule-mining.md` in the same pull request.
  When in doubt, score *up* — the model's contract is that it never flatters
  a command.
- **grantsmith prints, it never writes.** No subcommand may modify the
  user's settings file; adopting rules stays an explicit action by the user.
- **Every public API needs an English docstring and a test.** The bundled
  sample transcripts are pinned by `tests/test_examples.py`, so README
  output, the demo SVG, and the code cannot drift apart.
- **Keep the three READMEs aligned.** `README.md`, `README.zh.md`, and
  `README.ja.md` share the same structure line for line; update all three
  when you change one (English is the authoritative version).

## Reporting bugs

Please include the `grantsmith --version` output, the exact command line,
and — if you can share it — a minimal transcript snippet (a few JSONL
lines) that reproduces the wrong proposal or the wrong tier. For risk-tier
disagreements, `grantsmith explain "RULE" --json` output says exactly what
the model concluded and why.

## Security

Please do not report security issues in public GitHub issues. Use GitHub's
private vulnerability reporting on this repository instead.
