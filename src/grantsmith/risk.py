"""The risk model: every proposed rule gets a tier and human-readable reasons.

Five tiers, from ``safe`` (read-only, no side effects) to ``critical``
(irreversible or privilege-escalating). The model is a table of command
stems plus a handful of escalators for dangerous argument shapes
(``rm -rf``, ``git push --force``, ``sh -c``), shell constructs
(substitution, redirection), and rule breadth (a ``Bash(git:*)`` prefix is
scored by the worst subcommand it reaches, not by ``git`` alone).

The model is intentionally opinionated and fully inspectable:
``grantsmith explain RULE`` prints exactly what this module computed, and
`docs/rule-mining.md` documents every escalator. Unknown commands and
unknown tools default to ``medium`` — honest uncertainty, not optimism.
"""

from __future__ import annotations

import posixpath
import shlex
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .rules import Rule
from .shellparse import (
    FLAG_REDIRECT,
    FLAG_SUBSTITUTION,
    FLAG_UNPARSED,
    Segment,
    parse_command,
)

__all__ = [
    "Assessment",
    "TIERS",
    "assess_rule",
    "assess_segment",
    "path_sensitivity",
    "prefix_reach",
    "tier_index",
]

TIERS: Tuple[str, ...] = ("safe", "low", "medium", "high", "critical")
_TIER_INDEX: Dict[str, int] = {t: i for i, t in enumerate(TIERS)}


def tier_index(tier: str) -> int:
    """Position of *tier* in :data:`TIERS`; unknown strings sort worst."""
    return _TIER_INDEX.get(tier, len(TIERS))


@dataclass(frozen=True)
class Assessment:
    """The verdict for one rule or command segment."""

    tier: str
    reasons: Tuple[str, ...]

    def at_least(self, tier: str, reason: str) -> "Assessment":
        """Raise this assessment to *tier* if it is currently milder."""
        if tier_index(tier) > tier_index(self.tier):
            return Assessment(tier, self.reasons + (reason,))
        return Assessment(self.tier, self.reasons + (reason,))


def _worst(a: str, b: str) -> str:
    return a if tier_index(a) >= tier_index(b) else b


# ---------------------------------------------------------------------------
# Bash command table — longest stem wins (`git push` beats `git`).
# ---------------------------------------------------------------------------

BASH_TABLE: Dict[str, Tuple[str, str]] = {
    # multi-subcommand tools: the bare head is scored by its mildest honest
    # summary; specific subcommands below override via longest-prefix match.
    "git": ("medium", "subcommands range from queries to remote pushes"),
    "npm": ("medium", "package manager; can install and run scripts"),
    "pnpm": ("medium", "package manager; can install and run scripts"),
    "pip": ("medium", "package manager"),
    "pip3": ("medium", "package manager"),
    "cargo": ("medium", "build tool and package manager"),
    "go": ("medium", "toolchain; can fetch and run code"),
    "uv": ("medium", "package manager"),
    "poetry": ("medium", "package manager"),
    "brew": ("medium", "system package manager"),
    "apt": ("high", "system package manager"),
    "apt-get": ("high", "system package manager"),
    # read-only inspection
    "ls": ("safe", "lists directory contents"),
    "pwd": ("safe", "prints the working directory"),
    "cat": ("safe", "reads files"),
    "head": ("safe", "reads files"),
    "tail": ("safe", "reads files"),
    "wc": ("safe", "counts lines/words"),
    "echo": ("safe", "prints its arguments"),
    "printf": ("safe", "prints its arguments"),
    "which": ("safe", "locates executables"),
    "type": ("safe", "describes a command name"),
    "whoami": ("safe", "prints the current user"),
    "id": ("safe", "prints user identity"),
    "date": ("safe", "prints the date"),
    "uname": ("safe", "prints system information"),
    "stat": ("safe", "prints file metadata"),
    "file": ("safe", "identifies file types"),
    "du": ("safe", "reports disk usage"),
    "df": ("safe", "reports free space"),
    "tree": ("safe", "lists a directory tree"),
    "basename": ("safe", "string manipulation only"),
    "dirname": ("safe", "string manipulation only"),
    "realpath": ("safe", "resolves paths"),
    "printenv": ("safe", "prints environment variables"),
    "env": ("safe", "prints environment variables"),
    "grep": ("safe", "searches file contents"),
    "rg": ("safe", "searches file contents"),
    "egrep": ("safe", "searches file contents"),
    "fgrep": ("safe", "searches file contents"),
    "sort": ("safe", "reads stdin/files"),
    "uniq": ("safe", "reads stdin/files"),
    "cut": ("safe", "reads stdin/files"),
    "tr": ("safe", "reads stdin/files"),
    "jq": ("safe", "transforms JSON on stdout"),
    "diff": ("safe", "compares files"),
    "cmp": ("safe", "compares files"),
    "md5sum": ("safe", "hashes files"),
    "sha256sum": ("safe", "hashes files"),
    "awk": ("safe", "text processing on stdout"),
    "column": ("safe", "formats text"),
    "nl": ("safe", "numbers lines"),
    "seq": ("safe", "prints number sequences"),
    "true": ("safe", "no effect"),
    "false": ("safe", "no effect"),
    "sleep": ("safe", "waits; no side effects"),
    "find": ("safe", "searches the filesystem"),
    # git — reads
    "git status": ("safe", "read-only git query"),
    "git log": ("safe", "read-only git query"),
    "git diff": ("safe", "read-only git query"),
    "git show": ("safe", "read-only git query"),
    "git blame": ("safe", "read-only git query"),
    "git branch": ("safe", "lists branches (creation is local and cheap)"),
    "git describe": ("safe", "read-only git query"),
    "git rev-parse": ("safe", "read-only git query"),
    "git ls-files": ("safe", "read-only git query"),
    "git shortlog": ("safe", "read-only git query"),
    "git grep": ("safe", "read-only git query"),
    "git remote": ("safe", "lists remotes"),
    "git remote add": ("medium", "changes repository configuration"),
    "git stash list": ("safe", "read-only git query"),
    "git tag": ("low", "can create local tags"),
    # git — local mutation
    "git fetch": ("low", "contacts a remote, updates refs only"),
    "git pull": ("medium", "merges remote changes into the working tree"),
    "git add": ("medium", "stages files"),
    "git commit": ("medium", "creates local commits"),
    "git checkout": ("medium", "can overwrite working-tree changes"),
    "git switch": ("medium", "changes branches"),
    "git restore": ("medium", "discards working-tree changes"),
    "git merge": ("medium", "rewrites the working tree"),
    "git rebase": ("medium", "rewrites local history"),
    "git cherry-pick": ("medium", "rewrites local history"),
    "git stash": ("medium", "moves working-tree changes aside"),
    "git config": ("medium", "changes repository configuration"),
    "git apply": ("medium", "patches the working tree"),
    # git — remote / destructive
    "git push": ("high", "publishes commits to a remote"),
    "git reset": ("high", "can discard commits and changes"),
    "git clean": ("high", "deletes untracked files"),
    # package managers & builds
    "npm test": ("low", "runs the project test script"),
    "npm run": ("low", "runs a package script defined by the project"),
    "npm ls": ("safe", "read-only dependency query"),
    "npm install": ("medium", "installs packages and runs lifecycle scripts"),
    "npm ci": ("medium", "installs packages and runs lifecycle scripts"),
    "npm publish": ("critical", "publishes to a registry"),
    "npx": ("high", "downloads and executes packages"),
    "yarn": ("medium", "package manager; can install and run scripts"),
    "yarn run": ("low", "runs a package script defined by the project"),
    "pnpm run": ("low", "runs a package script defined by the project"),
    "pnpm install": ("medium", "installs packages and runs lifecycle scripts"),
    "pip install": ("medium", "installs packages (setup code may run)"),
    "pip3 install": ("medium", "installs packages (setup code may run)"),
    "pip list": ("safe", "read-only dependency query"),
    "pip show": ("safe", "read-only dependency query"),
    "uv run": ("low", "runs a project command in the managed env"),
    "uv pip": ("medium", "installs packages"),
    "poetry install": ("medium", "installs packages"),
    "poetry run": ("low", "runs a project command in the managed env"),
    "cargo build": ("low", "compiles the project (build scripts run)"),
    "cargo test": ("low", "runs the project test suite"),
    "cargo check": ("low", "type-checks the project"),
    "cargo clippy": ("low", "lints the project"),
    "cargo fmt": ("medium", "rewrites source files in place"),
    "cargo run": ("medium", "runs the project binary"),
    "cargo install": ("medium", "installs binaries into the toolchain"),
    "cargo publish": ("critical", "publishes to a registry"),
    "go build": ("low", "compiles the project"),
    "go test": ("low", "runs the project test suite"),
    "go vet": ("low", "lints the project"),
    "go run": ("medium", "runs project code"),
    "go install": ("medium", "fetches and installs binaries"),
    "make": ("medium", "runs arbitrary recipes from the Makefile"),
    "pytest": ("low", "runs the project test suite"),
    "tox": ("low", "runs the project test matrix"),
    "python -m pytest": ("low", "runs the project test suite"),
    "python3 -m pytest": ("low", "runs the project test suite"),
    "python": ("medium", "executes Python code"),
    "python3": ("medium", "executes Python code"),
    "node": ("medium", "executes JavaScript code"),
    "tsc": ("low", "type-checks / compiles TypeScript"),
    "eslint": ("low", "lints the project"),
    "ruff check": ("low", "lints the project"),
    "ruff format": ("medium", "rewrites source files in place"),
    "mypy": ("low", "type-checks the project"),
    "black": ("medium", "rewrites source files in place"),
    "prettier": ("medium", "can rewrite source files in place"),
    "xcodegen": ("medium", "regenerates project files"),
    # filesystem mutation
    "mkdir": ("medium", "creates directories"),
    "touch": ("medium", "creates/updates files"),
    "cp": ("medium", "copies files (can overwrite)"),
    "mv": ("medium", "moves files (can overwrite)"),
    "ln": ("medium", "creates links"),
    "tar": ("medium", "packs/unpacks archives"),
    "zip": ("medium", "packs archives"),
    "unzip": ("medium", "unpacks archives (can overwrite)"),
    "sed": ("medium", "-i rewrites files in place"),
    "tee": ("medium", "writes stdout to files"),
    "patch": ("medium", "patches files"),
    "rm": ("high", "deletes files"),
    "rmdir": ("medium", "removes empty directories"),
    "chmod": ("high", "changes file permissions"),
    "chown": ("high", "changes file ownership"),
    # processes & services
    "kill": ("high", "terminates processes"),
    "pkill": ("high", "terminates processes by name"),
    "killall": ("high", "terminates processes by name"),
    "crontab": ("high", "edits scheduled jobs"),
    "systemctl": ("high", "controls system services"),
    "launchctl": ("high", "controls system services"),
    "xargs": ("medium", "runs the command given in its arguments"),
    # network
    "curl": ("high", "network access: can download or exfiltrate"),
    "wget": ("high", "network access: can download files"),
    "ssh": ("high", "opens remote shells"),
    "scp": ("high", "copies files over the network"),
    "rsync": ("high", "syncs files, possibly over the network"),
    "nc": ("high", "raw network connections"),
    "ncat": ("high", "raw network connections"),
    "telnet": ("high", "raw network connections"),
    # infra / cloud
    "docker": ("high", "talks to the container daemon (root-equivalent)"),
    "kubectl": ("high", "mutates cluster state"),
    "kubectl get": ("low", "read-only cluster query"),
    "kubectl describe": ("low", "read-only cluster query"),
    "kubectl logs": ("low", "read-only cluster query"),
    "helm": ("high", "mutates cluster state"),
    "terraform": ("high", "can create/destroy infrastructure"),
    "aws": ("high", "cloud API access"),
    "gcloud": ("high", "cloud API access"),
    "az": ("high", "cloud API access"),
    # GitHub CLI
    "gh": ("medium", "GitHub API access"),
    "gh pr view": ("low", "read-only GitHub query"),
    "gh pr list": ("low", "read-only GitHub query"),
    "gh pr diff": ("low", "read-only GitHub query"),
    "gh issue view": ("low", "read-only GitHub query"),
    "gh issue list": ("low", "read-only GitHub query"),
    "gh run view": ("low", "read-only GitHub query"),
    "gh run list": ("low", "read-only GitHub query"),
    "gh repo view": ("low", "read-only GitHub query"),
    "gh api": ("high", "arbitrary GitHub API calls, including writes"),
    # shells & privilege
    "bash": ("high", "runs shell scripts"),
    "sh": ("high", "runs shell scripts"),
    "zsh": ("high", "runs shell scripts"),
    "source": ("medium", "executes a file in the current shell"),
    "eval": ("critical", "executes arbitrary constructed commands"),
    "exec": ("high", "replaces the current process"),
    "sudo": ("critical", "privilege escalation"),
    "su": ("critical", "privilege escalation"),
    "doas": ("critical", "privilege escalation"),
    "dd": ("critical", "raw device/file writes"),
    "mkfs": ("critical", "formats filesystems"),
    "shutdown": ("critical", "halts the machine"),
    "reboot": ("critical", "restarts the machine"),
}

_FORCE_FLAGS = frozenset({"-f", "--force"})
_RECURSIVE_FLAGS = frozenset({"-r", "-R", "--recursive"})
_SHELL_HEADS = frozenset({"bash", "sh", "zsh", "fish", "dash", "ksh"})


def _lookup_stem(tokens: Tuple[str, ...]) -> Tuple[str, Tuple[str, str]]:
    """Longest-prefix table lookup; returns (matched key, (tier, reason))."""
    for depth in range(min(len(tokens), 3), 0, -1):
        key = " ".join(tokens[:depth])
        if key in BASH_TABLE:
            return key, BASH_TABLE[key]
    head = tokens[0] if tokens else ""
    return head, ("medium", "unrecognized command `{}`".format(head or "?"))


def _rm_is_recursive_force(tokens: Tuple[str, ...]) -> bool:
    """True for rm with both recursive and force semantics (-rf, -fr, ...)."""
    recursive = force = False
    for tok in tokens[1:]:
        if tok in _RECURSIVE_FLAGS:
            recursive = True
        elif tok in _FORCE_FLAGS:
            force = True
        elif tok.startswith("-") and not tok.startswith("--"):
            letters = set(tok[1:])
            recursive = recursive or bool(letters & {"r", "R"})
            force = force or "f" in letters
    return recursive and force


def assess_segment(segment: Segment) -> Assessment:
    """Score one parsed command segment."""
    if segment.tokens is None or FLAG_UNPARSED in segment.flags:
        return Assessment(
            "high", ("command could not be parsed safely; review by hand",)
        )
    tokens = segment.tokens
    key, (tier, reason) = _lookup_stem(tokens)
    result = Assessment(tier, ("{}: {}".format(key, reason),))

    head = tokens[0]
    if head == "rm" and _rm_is_recursive_force(tokens):
        result = result.at_least("critical", "recursive force delete (`rm -rf`)")
    if key == "git push" and (set(tokens) & {"-f", "--force"}):
        result = result.at_least("critical", "force-push rewrites remote history")
    if head in _SHELL_HEADS and "-c" in tokens[1:]:
        result = result.at_least("critical", "executes an arbitrary inline script")
    if head == "find" and (set(tokens) & {"-delete", "-exec", "-execdir", "-ok"}):
        result = result.at_least("high", "find with -delete/-exec mutates or executes")
    if FLAG_SUBSTITUTION in segment.flags:
        result = result.at_least("medium", "contains command substitution `$(...)`")
    if FLAG_REDIRECT in segment.flags:
        result = result.at_least("low", "redirects to or from a file")
    return result


# ---------------------------------------------------------------------------
# Non-Bash tools
# ---------------------------------------------------------------------------

_SENSITIVE_PARTS = (
    ".env",
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "secrets",
    ".pem",
    ".p12",
)

_BROAD_PATTERNS = frozenset({"*", "**", "**/*", "//**", "~/**"})

_MCP_READ_VERBS = frozenset(
    {"get", "list", "read", "search", "query", "find", "describe", "show", "status"}
)


def path_sensitivity(pattern: str) -> Optional[str]:
    """Return the sensitive fragment a path/pattern touches, if any."""
    for part in posixpath.normpath(pattern).split("/"):
        low = part.lower()
        for marker in _SENSITIVE_PARTS:
            if low == marker or low.startswith(marker + ".") or low.endswith(marker):
                return marker
    return None


def _assess_file_rule(rule: Rule) -> Assessment:
    reads_only = rule.tool == "Read"
    base = (
        Assessment("safe", ("reads file contents only",))
        if reads_only
        else Assessment("medium", ("{} modifies files on disk".format(rule.tool),))
    )
    spec = rule.specifier
    if spec is None or spec in _BROAD_PATTERNS:
        if reads_only:
            return base.at_least(
                "medium", "matches every file, including credentials and dotfiles"
            )
        return base.at_least("high", "matches every file in the project and beyond")
    if ".." in spec.split("/"):
        base = base.at_least("high", "pattern escapes the project via `..`")
    marker = path_sensitivity(spec)
    if marker:
        base = base.at_least(
            "high", "touches `{}`: likely credentials or secrets".format(marker)
        )
    return base


def _assess_bash_rule(rule: Rule) -> Assessment:
    if rule.specifier is None:
        return Assessment(
            "critical", ("allows every shell command without a prompt",)
        )
    if not rule.prefix:
        segments = parse_command(rule.specifier)
        if not segments:
            return Assessment("high", ("empty command",))
        worst = Assessment("safe", ())
        for seg in segments:
            a = assess_segment(seg)
            if tier_index(a.tier) >= tier_index(worst.tier):
                worst = Assessment(a.tier, worst.reasons + a.reasons)
            else:
                worst = Assessment(worst.tier, worst.reasons + a.reasons)
        return worst

    reach = prefix_reach(rule.specifier)
    return reach.at_least(
        "low",
        "prefix rule: any arguments after `{}` are allowed".format(rule.specifier),
    )


def prefix_reach(spec: str) -> Assessment:
    """Score what a ``Bash(spec:*)`` prefix can *reach*, without the generic
    prefix floor.

    The stem itself is scored, then widened by every table entry the prefix
    can still complete into (``git:*`` reaches ``git push``). The miner uses
    this as its generalization gate: a prefix whose reach is riskier than
    the observed evidence is never proposed.
    """
    try:
        stem = tuple(shlex.split(spec, posix=True))
    except ValueError:
        stem = ()
    if not stem:
        return Assessment("high", ("prefix could not be parsed safely",))
    key, (tier, reason) = _lookup_stem(stem)
    result = Assessment(tier, ("{}: {}".format(key, reason),))
    prefix = " ".join(stem)
    worst_key = ""
    worst_tier = result.tier
    for entry, (entry_tier, _entry_reason) in BASH_TABLE.items():
        if entry.startswith(prefix + " ") and tier_index(entry_tier) > tier_index(
            worst_tier
        ):
            worst_tier, worst_key = entry_tier, entry
    if worst_key:
        result = result.at_least(
            worst_tier, "prefix also reaches `{}` ({})".format(worst_key, worst_tier)
        )
    return result


def assess_rule(rule: Rule) -> Assessment:
    """Score a permission rule of any tool type."""
    if rule.is_mcp:
        if rule.mcp_server_wide:
            return Assessment(
                "medium",
                ("server-wide: allows every tool this server exposes, now and later",),
            )
        tool_part = rule.tool.split("__", 2)[-1]
        verb = tool_part.split("_", 1)[0].lower()
        if verb in _MCP_READ_VERBS:
            return Assessment(
                "low", ("name suggests a read-only MCP tool; verify with the server",)
            )
        return Assessment(
            "medium", ("third-party MCP tool; side effects are not statically known",)
        )
    if rule.tool == "Bash":
        return _assess_bash_rule(rule)
    if rule.tool in {"Read", "Edit", "Write", "NotebookEdit"}:
        return _assess_file_rule(rule)
    if rule.tool in {"Glob", "Grep"}:
        return Assessment("safe", ("read-only search over the project",))
    if rule.tool == "TodoWrite":
        return Assessment("safe", ("updates the agent's own task list",))
    if rule.tool == "WebSearch":
        return Assessment("low", ("search snippets from the web enter the context",))
    if rule.tool == "WebFetch":
        if rule.specifier and rule.specifier.startswith("domain:"):
            domain = rule.specifier[len("domain:") :]
            return Assessment(
                "medium",
                (
                    "fetches from `{}`; fetched content can steer the agent".format(
                        domain
                    ),
                ),
            )
        return Assessment("high", ("fetches from any domain on the internet",))
    if rule.tool == "Task":
        return Assessment(
            "low", ("spawns a sub-agent that still faces its own permission checks",)
        )
    return Assessment(
        "medium", ("unrecognized tool `{}`; review its effects".format(rule.tool),)
    )
