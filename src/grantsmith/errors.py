"""Exception hierarchy for grantsmith.

Every error raised on purpose by this package derives from
:class:`GrantsmithError`, so callers embedding the library can catch one
type. The CLI maps these to exit code 1 with a one-line message instead of
a traceback.
"""

from __future__ import annotations

__all__ = [
    "GrantsmithError",
    "RuleSyntaxError",
    "SettingsError",
    "TranscriptError",
]


class GrantsmithError(Exception):
    """Base class for all grantsmith errors."""


class TranscriptError(GrantsmithError):
    """A transcript path does not exist or cannot be read at all.

    Individual malformed JSONL lines never raise; they are counted and
    skipped so one corrupt line cannot hide an entire session's evidence.
    """


class RuleSyntaxError(GrantsmithError):
    """A permission rule string could not be parsed."""


class SettingsError(GrantsmithError):
    """A settings file exists but is not valid JSON / not an object."""
