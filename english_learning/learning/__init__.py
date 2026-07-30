"""Learning Domain (Phase 3A).

Server-authoritative learning qualifications, kept SEPARATE from the war-game Game Domain. The Game
Domain (game/*) sees only opaque qualification IDs — it never imports lesson content, subject names,
or grading rules from here. This package owns:

- qualifications.py : pure player qualification state (grant/has/missing) — idempotent.
- grading.py        : deterministic server-side grading for the migrated activity types.
- content.py        : safe loading of the authoritative lesson JSON (answer keys) for grading.
- registry.py + registry.json : qualificationId -> {lessonId, activity, title} content-pack config.
"""
