"""Reading and emitting agent-CLI ``settings.json`` permission blocks.

Two shapes are accepted when *reading* (both occur in the wild):

- ``{"permissions": {"allow": ["Bash(git status)", ...]}}``
- ``{"allow": [...]}`` at the top level.

When *emitting*, grantsmith always writes the canonical nested shape, with
sorted keys and a trailing newline, so the output diffs cleanly and can be
pasted (or merged with ``--merge``) into ``.claude/settings.json`` or any
compatible allowlist file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .errors import RuleSyntaxError, SettingsError
from .rules import Rule, parse_rule

__all__ = ["emit_snippet", "load_allowlist", "merge_settings", "render_settings"]


def _extract_allow(data: Dict[str, Any]) -> List[str]:
    permissions = data.get("permissions")
    if isinstance(permissions, dict) and isinstance(permissions.get("allow"), list):
        raw = permissions["allow"]
    elif isinstance(data.get("allow"), list):
        raw = data["allow"]
    else:
        raw = []
    return [item for item in raw if isinstance(item, str)]


def load_allowlist(path: str) -> Tuple[List[Rule], List[str]]:
    """Parse the allowlist in *path*.

    Returns ``(rules, unparsed)`` — rule strings grantsmith cannot parse
    are reported, not silently dropped, so a typo in your settings is
    surfaced instead of causing double-proposals.
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SettingsError("cannot read settings {}: {}".format(path, exc))
    except json.JSONDecodeError as exc:
        raise SettingsError("settings {} is not valid JSON: {}".format(path, exc))
    if not isinstance(data, dict):
        raise SettingsError("settings {} must be a JSON object".format(path))

    rules: List[Rule] = []
    unparsed: List[str] = []
    for text in _extract_allow(data):
        try:
            rules.append(parse_rule(text))
        except RuleSyntaxError:
            unparsed.append(text)
    return rules, unparsed


def emit_snippet(rules: Sequence[Rule]) -> Dict[str, Any]:
    """A minimal, mergeable settings fragment containing *rules*."""
    return {"permissions": {"allow": [str(r) for r in rules]}}


def merge_settings(path: str, rules: Sequence[Rule]) -> Dict[str, Any]:
    """The full settings file at *path* with *rules* appended.

    Existing entries keep their order; new rules are appended in ranked
    order, skipping exact duplicates. Everything else in the file is
    preserved untouched.
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SettingsError("cannot read settings {}: {}".format(path, exc))
    except json.JSONDecodeError as exc:
        raise SettingsError("settings {} is not valid JSON: {}".format(path, exc))
    if not isinstance(data, dict):
        raise SettingsError("settings {} must be a JSON object".format(path))

    permissions = data.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise SettingsError('"permissions" in {} must be an object'.format(path))
    allow = permissions.setdefault("allow", [])
    if not isinstance(allow, list):
        raise SettingsError('"permissions.allow" in {} must be a list'.format(path))
    have = {item for item in allow if isinstance(item, str)}
    for rule in rules:
        text = str(rule)
        if text not in have:
            allow.append(text)
            have.add(text)
    return data


def render_settings(data: Dict[str, Any]) -> str:
    """Stable JSON text for a settings object (2-space indent, newline)."""
    return json.dumps(data, indent=2, sort_keys=False) + "\n"
