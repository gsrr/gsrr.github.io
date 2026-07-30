"""Safe loading of authoritative lesson content (answer keys) for server-side grading.

Reads the SAME `<lessonId>.json` the client renders — the keys are already client-visible today, so
this does not expose anything new; it just lets the SERVER re-grade authoritatively. The caller
whitelists lesson ids via the qualification registry before loading; this module additionally guards
against path traversal so a crafted lessonId can never read outside CONTENT_ROOT.
"""
import json
import os


def load_lesson(lesson_id, content_root):
    """Return the parsed lesson JSON dict, or None if missing/invalid/outside the content root."""
    if not lesson_id or not content_root:
        return None
    rel = str(lesson_id).strip().lstrip("/\\")
    if not rel or ".." in rel.replace("\\", "/").split("/"):
        return None
    root = os.path.abspath(content_root)
    path = os.path.abspath(os.path.join(root, rel + ".json"))
    if path != root and not path.startswith(root + os.sep):   # must stay within CONTENT_ROOT
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
