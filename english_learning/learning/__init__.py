"""Learning Domain (Phase 3A slice → Phase 3B generalized model).

Server-authoritative learning progression, kept SEPARATE from the war-game Game Domain. The Game
Domain (game/*) sees only opaque qualification IDs — it never imports lesson content, subject names,
grading rules or reward amounts from here.

    identity.py       : stable logical IDs (pack/course/unit/lesson/activity) + legacy key parsing.
    registry.py       : the content-pack config — logical identity <-> content path, graders,
                        grants, reward policy, study targets. Includes the schema validator.
    registry.json     : the installed content-pack configuration (data, not code).
    content.py        : allowlisted, traversal-proof access to the authoritative lesson JSON.
    grading.py        : deterministic graders, dispatched by activity graderType (not by name).
    rewards.py        : server-owned reward POLICY allowlist — content can name one, never an amount.
    qualifications.py : pure player state (completions + qualifications), idempotent, many-to-many.
    api.py            : LearningService — the single facade the HTTP layer delegates to.

See docs/learning-model.md for the identity hierarchy, schema and trust boundaries.
"""
