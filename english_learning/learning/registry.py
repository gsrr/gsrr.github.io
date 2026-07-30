"""Qualification registry (content-pack config): qualificationId -> {lessonId, activity, title}.

Maps a server-graded activity to the OPAQUE qualification it grants, and provides a human-readable
title for the UI. This is Learning-Domain data — the Game Domain never imports it and only ever sees
opaque qualification IDs. A qualification ID is stable even if its `title` (UI text) changes.
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")
try:
    with open(_PATH, encoding="utf-8") as _f:
        REGISTRY = json.load(_f)
    if not isinstance(REGISTRY, dict):
        REGISTRY = {}
except Exception:
    REGISTRY = {}


def qualification_for(lesson_id, activity):
    """The qualification id granted by passing (lesson_id, activity), or None if not registered."""
    for qid, spec in REGISTRY.items():
        if spec.get("lessonId") == lesson_id and spec.get("activity") == activity:
            return qid
    return None


def spec(qid):
    return REGISTRY.get(qid)


def public_view():
    """id -> {lessonId, activity, title} for the frontend. Contains NO answer keys."""
    return {qid: {"lessonId": s.get("lessonId"), "activity": s.get("activity"), "title": s.get("title")}
            for qid, s in REGISTRY.items()}


def gradable_lesson_ids():
    return {s.get("lessonId") for s in REGISTRY.values() if s.get("lessonId")}
