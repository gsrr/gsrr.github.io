"""Safe loading of authoritative lesson content (answer keys) for server-side grading (§28).

Three independent gates stand between an HTTP request and a filesystem read:

  1. ALLOWLIST  — the path must be one the registry declares (`Registry.approved_content_paths()`).
                  A request path never reaches this module; only a registry-resolved path does.
  2. SHAPE      — identity.is_content_path() rejects absolute paths, backslashes and '.'/'..' segments.
  3. CONTAINMENT— the realpath must sit inside CONTENT_ROOT, so symlinks cannot escape either.

Reading the same `<contentPath>.json` the client renders exposes nothing new (the browser already
downloads it); it just lets the SERVER re-grade authoritatively.

CONTENT_ROOT determinism: the container sets it explicitly (Dockerfile `ENV CONTENT_ROOT`), while
local runs and tests default to the repo root next to server.py. Same lookup rule in all three.
"""
import json
import os
import re

from . import identity


def resolve_path(content_path, content_root, allowed_paths=None, suffix=".json"):
    """Absolute, contained path to `<content_path><suffix>`, or None if any gate rejects it.

    `suffix` is "" for the plain dialogue text file (the Read-Along source), which lives next to the
    activity JSON under the same registry-approved content path — so it passes the same three gates.
    """
    if not content_path or not content_root or not identity.is_content_path(content_path):
        return None
    if allowed_paths is not None and content_path not in allowed_paths:
        return None                                  # not declared by the registry -> never read
    root = os.path.realpath(os.path.abspath(content_root))
    path = os.path.realpath(os.path.abspath(os.path.join(root, content_path + suffix)))
    if path != root and not path.startswith(root + os.sep):
        return None
    return path


def load_lesson(content_path, content_root, allowed_paths=None):
    """The parsed lesson JSON dict, or None if refused/missing/invalid."""
    path = resolve_path(content_path, content_root, allowed_paths)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


_DIALOGUE_LINE = re.compile(r"^([^:：]+)[:：]\s*(.*)$")


def load_dialogue(content_path, content_root, allowed_paths=None):
    """The lesson's spoken script as a list of sentence strings, or None if unavailable.

    Exact port of index.html parseDialogue(): split on newlines, trim, drop blanks, keep only lines
    shaped `<speaker>: <text>`, and take the text. This is what makes the Read-Along target sentence
    server-resolvable — the client never gets to say what the target is.
    """
    path = resolve_path(content_path, content_root, allowed_paths, suffix="")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return None
    out = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _DIALOGUE_LINE.match(line)
        if m:
            out.append(m.group(2).strip())
    return out or None


def load_activity_items(content_path, content_key, content_root, allowed_paths=None):
    """The authoritative key items (a list) for one activity, or None if unavailable.

    `content_key` is the activity's key inside the lesson JSON (e.g. "quiz3") — it is registry data,
    never client input, and is only ever used as a dict lookup, so it cannot influence the path.
    """
    lesson = load_lesson(content_path, content_root, allowed_paths)
    if not isinstance(lesson, dict) or not content_key:
        return None
    items = lesson.get(content_key)
    return items if isinstance(items, list) and items else None
