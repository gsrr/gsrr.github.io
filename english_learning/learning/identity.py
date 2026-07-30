"""Learning identity — stable logical IDs, PURE (no I/O, no config).

The hierarchy is expressed purely by dotted segments, so a parent is always a prefix of its child:

    contentPack   english.prea1
    course        english.prea1.taipei
    unit          (optional — omitted by the current content; see docs/learning-model.md)
    lesson        english.prea1.taipei.zoo
    activity      english.prea1.taipei.zoo.quiz3
    qualification opaque to the Game Domain; conventionally derived from what it certifies

Not every content source must use every level: `unit` is skipped by today's content and the model
does not require it. Nothing here knows about English, quizzes or territories.

CONTENT PATH vs LOGICAL IDENTITY — the central Phase 3B separation. `Pre-A1/taipei/zoo` is a
*content path* (where the JSON lives on disk); `english.prea1.taipei.zoo` is a *logical lesson id*.
Only the registry maps one to the other. Renaming files therefore cannot invalidate a learner's
earned qualifications, and the Game Domain never sees a filesystem path.
"""
import re

# Dotted, lowercase, ≥1 segment. Segments allow digits/underscore/hyphen but must start alphanumeric.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)*$")
# One content-path segment: no separators, no dot-only names (blocks "." and "..").
_PATH_SEG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$")
LEGACY_SEP = "#"                      # Phase 3A completion key: "<contentPath>#<activity>"
SCOPES = ("activity", "lesson", "unit", "course")


def is_id(value):
    """True for a well-formed logical id (any level). Rejects empty/None/uppercase/spaces/traversal."""
    return bool(value) and isinstance(value, str) and bool(_ID_RE.match(value))


def segments(value):
    return value.split(".") if is_id(value) else []


def parent_id(value):
    """The enclosing level's id ('a.b.c' -> 'a.b'), or None for a single-segment/invalid id."""
    segs = segments(value)
    return ".".join(segs[:-1]) if len(segs) > 1 else None


def is_ancestor(ancestor, descendant):
    """Prefix containment on whole segments — 'a.b' contains 'a.b.c' but not 'a.bc'."""
    if not (is_id(ancestor) and is_id(descendant)):
        return False
    return descendant == ancestor or descendant.startswith(ancestor + ".")


def is_content_path(value):
    """True for a safe RELATIVE content path such as 'Pre-A1/taipei/zoo'.

    Rejects absolute paths, backslashes, '.'/'..' segments, empty segments and trailing slashes.
    This is a *shape* check only — the registry allowlist plus content.py's realpath containment
    check are what actually keep filesystem reads inside CONTENT_ROOT.
    """
    if not value or not isinstance(value, str) or "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    return bool(parts) and all(_PATH_SEG_RE.match(p) and p not in (".", "..") for p in parts)


def legacy_completion_key(content_path, content_key):
    """The Phase 3A activity-completion key. Kept so old records stay readable forever."""
    if not content_path or not content_key:
        return None
    return "%s%s%s" % (content_path, LEGACY_SEP, content_key)


def split_legacy_completion_key(key):
    """'Pre-A1/taipei/zoo#quiz3' -> ('Pre-A1/taipei/zoo', 'quiz3'); (None, None) if not legacy-shaped."""
    if not key or not isinstance(key, str) or key.count(LEGACY_SEP) != 1:
        return None, None
    path, _, act = key.partition(LEGACY_SEP)
    return (path, act) if (path and act) else (None, None)


def looks_legacy(key):
    return split_legacy_completion_key(key)[0] is not None
