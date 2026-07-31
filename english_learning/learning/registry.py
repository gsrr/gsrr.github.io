"""Learning registry — the content-pack configuration that maps content to logical identity.

This is Learning-Domain data. The Game Domain never imports it and only ever sees opaque
qualification IDs. Schema (see docs/learning-model.md for the full contract):

    {
      "schemaVersion": 1,
      "contentPacks": { "<packId>":   {"title": ...} },
      "courses":      { "<courseId>": {"contentPackId": ..., "title": ..., "unitId": <optional>} },
      "units":        { "<unitId>":   {"courseId": ..., "title": ...} },              # optional level
      "lessons":      { "<lessonId>": {"courseId": ..., "contentPath": ..., "title": ...,
                                       "unitId": <optional>,
                                       "completionPolicy": <optional>,
                                       "retiredCompletionPolicyVersions": [<optional ints>]} },
      "activities":   { "<activityId>": {"lessonId": ..., "contentKey": ..., "graderType": ...,
                                         "title": ..., "grants": [...], "rewardPolicy": ...,
                                         "legacyKeys": [...]} },
      "qualifications": { "<qualificationId>": {"scope": "activity|lesson|unit|course",
                                                "title": ..., "studyTarget": <optional override>} }
    }

Deliberately NOT in here: answer keys (the authoritative lesson JSON already owns them, so
duplicating them would create a second source of truth) and reward AMOUNTS (see rewards.py §15).
"""
import json
import os

from . import completion, grading, identity, matching, rewards, stt_scoring

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")
SCHEMA_VERSION = 1
_SECTIONS = ("contentPacks", "courses", "units", "lessons", "activities", "qualifications")
# graderConfig keys the graders actually read (learning/grading.py). Anything else is an authoring bug.
_GRADER_CFG_KEYS = {"promptField", "answerField", "distractorsField", "joinWith"}
# Phase 3D: keys allowed inside a lesson's optional completionPolicy.
_COMPLETION_KEYS = {"type", "version", "requiredActivityIds", "grants", "rewardPolicy",
                    "passMark"}
# Phase 3E1: non-deterministic scorers live outside the GRADERS table (§8).
_SCORER_TYPES = {stt_scoring.SCORER_TYPE, matching.SCORER_TYPE}
_SCORED_KIND = {stt_scoring.SCORER_TYPE: "stt", matching.SCORER_TYPE: "matching"}


def _no_dup_keys(pairs):
    """json object hook: a duplicated key is a registry authoring error, not a silent last-wins."""
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError("duplicate key %r in learning registry" % k)
        seen[k] = v
    return seen


class Registry:
    """An immutable-by-convention view over registry data. Constructible from a dict for tests."""

    def __init__(self, data=None):
        data = data if isinstance(data, dict) else {}
        self.schema_version = data.get("schemaVersion", SCHEMA_VERSION)
        for s in _SECTIONS:
            setattr(self, _attr(s), data.get(s) if isinstance(data.get(s), dict) else {})
        # derived indexes (built once; every lookup below is O(1) and never scans)
        self._by_legacy = {}
        self._by_content = {}
        for aid, a in self.activities.items():
            for lk in (a.get("legacyKeys") or []):
                self._by_legacy.setdefault(lk, aid)
            path = self.content_path_of(aid)
            if path:
                self._by_content.setdefault((path, a.get("contentKey")), aid)
        self._granted_by = {}
        for aid, a in self.activities.items():
            for qid in (a.get("grants") or []):
                self._granted_by.setdefault(qid, []).append(aid)

    # ---- raw lookups ----
    def activity(self, activity_id):
        return self.activities.get(activity_id)

    def lesson(self, lesson_id):
        return self.lessons.get(lesson_id)

    def course(self, course_id):
        return self.courses.get(course_id)

    def unit(self, unit_id):
        return self.units.get(unit_id)

    def content_pack(self, pack_id):
        return self.contentPacks.get(pack_id)

    def qualification(self, qid):
        return self.qualifications.get(qid)

    # ---- resolution ----
    def content_path_of(self, activity_id):
        """The on-disk content path for an activity, via its lesson. None if unmapped."""
        a = self.activities.get(activity_id) or {}
        les = self.lessons.get(a.get("lessonId")) or {}
        return les.get("contentPath")

    def resolve_activity_id(self, activity_id=None, lesson_id=None, activity=None):
        """Canonical activityId from either the canonical id or a legacy (lessonId, activity) pair.

        Accepted, in order: a known canonical activityId; a legacy completion key; a
        logical lessonId + contentKey; a CONTENT PATH + contentKey (what the Phase 3A client sends).
        Returns None for anything unknown — an unregistered id is never fabricated, so the registry
        stays the single whitelist for grading and filesystem access.
        """
        if activity_id and activity_id in self.activities:
            return activity_id
        if activity_id and activity_id in self._by_legacy:
            return self._by_legacy[activity_id]
        if lesson_id and activity:
            key = identity.legacy_completion_key(lesson_id, activity)
            if key in self._by_legacy:
                return self._by_legacy[key]
            for aid, a in self.activities.items():          # logical lessonId + contentKey
                if a.get("lessonId") == lesson_id and a.get("contentKey") == activity:
                    return aid
            hit = self._by_content.get((lesson_id, activity))   # content path + contentKey
            if hit:
                return hit
        return None

    def legacy_keys_for(self, activity_id):
        a = self.activities.get(activity_id) or {}
        return list(a.get("legacyKeys") or [])

    def qualification_ids_for(self, activity_id):
        """The opaque qualification IDs granted by passing this activity (order preserved)."""
        a = self.activities.get(activity_id) or {}
        return [q for q in (a.get("grants") or []) if q]

    def granted_by(self, qid):
        """Which activities can grant this qualification (a qualification may have several routes)."""
        return list(self._granted_by.get(qid) or [])

    def reward_policy_of(self, activity_id):
        a = self.activities.get(activity_id) or {}
        return a.get("rewardPolicy") or rewards.DEFAULT_POLICY

    def grader_type_of(self, activity_id):
        return (self.activities.get(activity_id) or {}).get("graderType")

    def scorer_type_of(self, activity_id):
        """Non-deterministic scorer (Phase 3E1 Read-Along/STT). Mutually exclusive with graderType."""
        return (self.activities.get(activity_id) or {}).get("scorerType")

    def is_server_scored(self, activity_id):
        """True if the server produces the authoritative result for this activity, either way."""
        a = self.activities.get(activity_id) or {}
        return grading.is_supported(a.get("graderType")) or a.get("scorerType") in _SCORER_TYPES

    def grader_config_of(self, activity_id):
        """Registry-owned grader configuration (field names etc.). Never client input."""
        cfg = (self.activities.get(activity_id) or {}).get("graderConfig")
        return dict(cfg) if isinstance(cfg, dict) else {}

    # ---- lesson completion (Phase 3D) ----
    def completion_policy_of(self, lesson_id):
        """The lesson's completion policy, or None when authoritative completion is unavailable."""
        return completion.policy_of(self.lessons.get(lesson_id))

    def completion_available(self, lesson_id):
        return completion.is_available(self.lessons.get(lesson_id))

    def retired_policy_versions(self, lesson_id):
        """Policy versions this lesson has already SPENT in production (Phase 4B).

        Learners may hold `lessonCompletions` records stamped with these versions; the records stay
        valid history and are never rewritten. A future policy must pick an unused version so a
        record's version always identifies the rule that produced it.
        """
        v = (self.lessons.get(lesson_id) or {}).get("retiredCompletionPolicyVersions")
        return sorted(x for x in v if isinstance(x, int) and not isinstance(x, bool)) \
            if isinstance(v, list) else []

    def lesson_of_activity(self, activity_id):
        return (self.activities.get(activity_id) or {}).get("lessonId")

    def lesson_qualification_ids_for(self, lesson_id):
        return completion.grants_of(self.completion_policy_of(lesson_id))

    def lesson_reward_policy_of(self, lesson_id):
        return completion.reward_policy_of(self.completion_policy_of(lesson_id))

    def approved_content_paths(self):
        """The ONLY content paths the backend may ever read (§28). Registry == filesystem allowlist."""
        return {l.get("contentPath") for l in self.lessons.values() if l.get("contentPath")}

    def study_target(self, qid):
        """Where a learner should go to earn `qid` — {lessonId, activityId, contentPath, title}.

        Derived from the granting activity so it can never drift out of sync; a qualification may
        override it explicitly. None when nothing currently grants the qualification (e.g. a
        reserved lesson/course-scope qualification, or a requirement whose pack is not installed).
        """
        q = self.qualifications.get(qid) or {}
        override = q.get("studyTarget")
        if isinstance(override, dict) and override.get("activityId") in self.activities:
            aid = override["activityId"]
        else:
            routes = self.granted_by(qid)
            if not routes:
                return None
            aid = sorted(routes)[0]                 # deterministic when several routes exist
        a = self.activities.get(aid) or {}
        return {"activityId": aid, "lessonId": a.get("lessonId"),
                "contentPath": self.content_path_of(aid), "title": a.get("title")}

    def title_of_qualification(self, qid):
        q = self.qualifications.get(qid) or {}
        if q.get("title"):
            return q["title"]
        tgt = self.study_target(qid)
        return (tgt or {}).get("title") or qid       # last resort: the opaque id itself

    # ---- frontend view (never carries answer keys, grader internals or reward amounts) ----
    def public_view(self):
        return {
            "schemaVersion": self.schema_version,
            "qualifications": {qid: {"scope": q.get("scope") or "activity",
                                     "title": self.title_of_qualification(qid),
                                     "studyTarget": self.study_target(qid)}
                               for qid, q in self.qualifications.items()},
            # `serverGraded` tells the client whether this activity goes through the authoritative
            # attempt endpoint (§18). Grader type, grader config and reward policy stay server-side.
            "activities": {aid: {"lessonId": a.get("lessonId"),
                                 "contentPath": self.content_path_of(aid),
                                 "contentKey": a.get("contentKey"),
                                 "title": a.get("title"),
                                 "serverGraded": self.is_server_scored(aid),
                                 "scored": _SCORED_KIND.get(a.get("scorerType"), "deterministic"),
                                 "grants": self.qualification_ids_for(aid)}
                           for aid, a in self.activities.items()},
            # `authoritativeCompletionAvailable` is false for every production lesson in Phase 3D —
            # the client must therefore NOT present those lessons as "incomplete"; it simply has no
            # authoritative answer for them and keeps using its existing legacy display.
            "lessons": {lid: {"courseId": l.get("courseId"), "contentPath": l.get("contentPath"),
                              "title": l.get("title"),
                              "authoritativeCompletionAvailable": completion.is_available(l)}
                        for lid, l in self.lessons.items()},
        }


def _attr(section):
    return section


# ======================= validation (§26) — pure, operates on a raw dict =======================
def validate(data):
    """Return a list of human-readable error strings; empty means valid.

    Structural + referential + trust-boundary checks. Never raises, never touches the filesystem,
    so it is usable from the CLI validator and from unit tests on synthetic registries alike.
    """
    errs = []

    def err(msg):
        errs.append(msg)

    if not isinstance(data, dict):
        return ["registry must be a JSON object"]
    if data.get("schemaVersion") != SCHEMA_VERSION:
        err("schemaVersion must be %d (got %r)" % (SCHEMA_VERSION, data.get("schemaVersion")))
    unknown = set(data) - set(_SECTIONS) - {"schemaVersion"}
    if unknown:
        err("unknown top-level sections: %s" % sorted(unknown))
    sec = {}
    for s in _SECTIONS:
        v = data.get(s, {})
        if not isinstance(v, dict):
            err("%s must be an object" % s)
            v = {}
        sec[s] = v
    packs, courses, units = sec["contentPacks"], sec["courses"], sec["units"]
    lessons, activities, quals = sec["lessons"], sec["activities"], sec["qualifications"]

    for name, table in (("contentPack", packs), ("course", courses), ("unit", units),
                        ("lesson", lessons), ("activity", activities), ("qualification", quals)):
        for key in table:
            if not identity.is_id(key):
                err("%s id %r is empty or malformed (expect dotted lowercase segments)" % (name, key))

    for cid, c in courses.items():
        if (c or {}).get("contentPackId") not in packs:
            err("course %s references unknown contentPackId %r" % (cid, (c or {}).get("contentPackId")))
    for uid, u in units.items():
        if (u or {}).get("courseId") not in courses:
            err("unit %s references unknown courseId %r" % (uid, (u or {}).get("courseId")))

    lesson_granted = set()
    for lid, l in lessons.items():
        l = l or {}
        if l.get("courseId") not in courses:
            err("lesson %s references unknown courseId %r" % (lid, l.get("courseId")))
        if l.get("unitId") is not None and l.get("unitId") not in units:
            err("lesson %s references unknown unitId %r" % (lid, l.get("unitId")))
        if not identity.is_content_path(l.get("contentPath")):
            err("lesson %s has a missing/malformed contentPath %r" % (lid, l.get("contentPath")))
        # ---- Phase 4B: retired policy versions (OPTIONAL) ----
        # A version number is spent once it has been active in production: learners may hold
        # lessonCompletions stamped with it, and those records mean whatever that policy meant. A
        # later policy with different semantics must therefore take a NEW version, never reuse one.
        retired = l.get("retiredCompletionPolicyVersions")
        if retired is not None:
            if not isinstance(retired, list) or not retired:
                err("lesson %s retiredCompletionPolicyVersions must be a non-empty list" % lid)
            else:
                seen_v = set()
                for v in retired:
                    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                        err("lesson %s has a malformed retired policy version %r" % (lid, v))
                    elif v in seen_v:
                        err("lesson %s lists retired policy version %r twice" % (lid, v))
                    seen_v.add(v)
        # ---- Phase 3D completion policy (OPTIONAL; absent == authoritative completion unavailable) ----
        if "completionPolicy" not in l or l.get("completionPolicy") is None:
            continue
        cp = l.get("completionPolicy")
        if not isinstance(cp, dict):
            err("lesson %s completionPolicy must be an object (or absent)" % lid)
            continue
        unknown_cp = set(cp) - _COMPLETION_KEYS
        if unknown_cp:
            err("lesson %s completionPolicy has unknown keys %s" % (lid, sorted(unknown_cp)))
        if cp.get("type") not in completion.POLICY_TYPES:
            err("lesson %s completionPolicy has unknown type %r (known: %s)"
                % (lid, cp.get("type"), list(completion.POLICY_TYPES)))
        ver = cp.get("version")
        if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
            err("lesson %s completionPolicy.version must be a positive integer" % lid)
        elif isinstance(retired, list) and ver in retired:
            err("lesson %s completionPolicy reuses retired policy version %d — historical "
                "lessonCompletions carry that version and mean what the OLD policy meant, so a "
                "policy with different semantics must take a new version" % (lid, ver))
        req = cp.get("requiredActivityIds")
        if not isinstance(req, list) or not req:
            err("lesson %s completionPolicy must list at least one requiredActivityId" % lid)
            req = []
        if len(req) != len(set(req)):
            err("lesson %s completionPolicy lists a duplicate requiredActivityId" % lid)
        for aid in req:
            if not identity.is_id(aid):
                err("lesson %s completionPolicy requiredActivityId %r is malformed" % (lid, aid))
            elif aid not in activities:
                err("lesson %s completionPolicy requires unknown activity %r" % (lid, aid))
            elif (activities[aid] or {}).get("lessonId") != lid:
                err("lesson %s completionPolicy requires %s, which belongs to lesson %r"
                    % (lid, aid, (activities[aid] or {}).get("lessonId")))
        # §4/§6: a restated threshold may never WEAKEN the trusted one, and every required activity
        # must have a server-side evidence source that can supply an exact correct/total pair.
        if "passMark" in cp and cp.get("passMark") != completion.PASS_MARK:
            err("lesson %s completionPolicy.passMark must be %d (the authoritative PASS_MARK), got %r"
                % (lid, completion.PASS_MARK, cp.get("passMark")))
        if cp.get("type") == "average_required_activities":
            for aid in req:
                a = activities.get(aid) or {}
                sct, gt = a.get("scorerType"), a.get("graderType")
                if not (sct in _SCORER_TYPES or grading.is_supported(gt)):
                    err("lesson %s averages %s, which has no server-side evidence source" % (lid, aid))
        for money in ("rewardGold", "gold", "rewardAmount", "amount"):
            if money in cp:                 # §15 again: content may NAME a policy, never an amount
                err("lesson %s completionPolicy may not set %r — reward amounts come from game config "
                    "only" % (lid, money))
        if not rewards.is_policy(completion.reward_policy_of(cp)):
            err("lesson %s completionPolicy has invalid rewardPolicy %r (allowed: %s)"
                % (lid, cp.get("rewardPolicy"), rewards.policy_ids()))
        lg = cp.get("grants", [])
        if not isinstance(lg, list):
            err("lesson %s completionPolicy grants must be a list (may be empty)" % lid)
            lg = []
        if len(lg) != len(set(lg)):
            err("lesson %s completionPolicy lists a duplicate qualification in grants" % lid)
        for qid in lg:
            if qid not in quals:
                err("lesson %s completionPolicy grants unknown qualification %r" % (lid, qid))
            elif (quals[qid] or {}).get("scope") != "lesson":
                # a lesson may only certify a lesson-scope qualification, and vice versa
                err("lesson %s completionPolicy grants %s whose scope is %r — expected 'lesson'"
                    % (lid, qid, (quals[qid] or {}).get("scope")))
            else:
                lesson_granted.add(qid)

    seen_legacy = {}
    for aid, a in activities.items():
        a = a or {}
        if a.get("lessonId") not in lessons:
            err("activity %s references unknown lessonId %r" % (aid, a.get("lessonId")))
        if a.get("scorerType") is None and (not a.get("contentKey") or
                                            not isinstance(a.get("contentKey"), str)):
            err("activity %s has a missing/invalid contentKey" % aid)
        gt, sct = a.get("graderType"), a.get("scorerType")
        if gt is not None and sct is not None:
            err("activity %s declares both graderType and scorerType — exactly one is allowed" % aid)
        elif sct is not None:
            if sct not in _SCORER_TYPES:
                err("activity %s has unknown scorerType %r (known: %s)"
                    % (aid, sct, sorted(_SCORER_TYPES)))
            if sct == stt_scoring.SCORER_TYPE and a.get("contentKey") is not None:
                err("activity %s uses scorerType %r, whose content is the lesson dialogue — it must "
                    "not declare a contentKey" % (aid, sct))
            if sct == matching.SCORER_TYPE and not isinstance(a.get("contentKey"), str):
                err("activity %s uses scorerType %r and must name the content key holding its "
                    "word/picture pairs (e.g. \"vocab\")" % (aid, sct))
            if a.get("graderConfig") is not None:
                err("activity %s uses scorerType %r and must not declare graderConfig" % (aid, sct))
        elif not grading.is_supported(gt):
            err("activity %s has unknown graderType %r (known: %s)"
                % (aid, gt, grading.grader_types()))
        if not a.get("title"):
            err("activity %s has no title" % aid)
        if not rewards.is_policy(a.get("rewardPolicy") or rewards.DEFAULT_POLICY):
            err("activity %s has invalid rewardPolicy %r (allowed: %s)"
                % (aid, a.get("rewardPolicy"), rewards.policy_ids()))
        for money in ("rewardGold", "gold", "rewardAmount", "amount"):
            if money in a:                       # §15: content may NAME a policy, never an amount
                err("activity %s may not set %r — reward amounts come from game config only" % (aid, money))
        gcfg = a.get("graderConfig")
        if gcfg is not None:
            if not isinstance(gcfg, dict):
                err("activity %s graderConfig must be an object" % aid)
            else:
                unknown_cfg = set(gcfg) - _GRADER_CFG_KEYS
                if unknown_cfg:
                    err("activity %s graderConfig has unknown keys %s" % (aid, sorted(unknown_cfg)))
                for k, v in gcfg.items():
                    if not isinstance(v, str) or not v:
                        err("activity %s graderConfig.%s must be a non-empty string" % (aid, k))
        # Phase 3C §24: server grading does NOT imply a qualification. `grants` may be empty — but it
        # must still be a list, and every id in it must exist.
        grants = a.get("grants", [])
        if not isinstance(grants, list):
            err("activity %s grants must be a list (may be empty)" % aid)
            grants = []
        if len(grants) != len(set(grants)):
            err("activity %s lists a duplicate qualification in grants" % aid)
        for qid in grants:
            if qid not in quals:
                err("activity %s grants unknown qualification %r" % (aid, qid))
            elif (quals[qid] or {}).get("scope", "activity") != "activity":
                # §7: only what the server can actually prove may be earnable today.
                err("activity %s grants %s whose scope is %r — only 'activity' scope is earnable "
                    "until authoritative aggregation exists" % (aid, qid, (quals[qid] or {}).get("scope")))
        for lk in (a.get("legacyKeys") or []):
            if not identity.looks_legacy(lk):
                err("activity %s has malformed legacyKey %r (expect '<contentPath>#<contentKey>')" % (aid, lk))
            elif lk in seen_legacy:
                err("legacyKey %r is claimed by both %s and %s" % (lk, seen_legacy[lk], aid))
            else:
                seen_legacy[lk] = aid

    granted = set()
    for a in activities.values():
        granted.update((a or {}).get("grants") or [])
    for qid, q in quals.items():
        q = q or {}
        scope = q.get("scope", "activity")
        if scope not in identity.SCOPES:
            err("qualification %s has invalid scope %r (allowed: %s)" % (qid, scope, list(identity.SCOPES)))
        tgt = q.get("studyTarget")
        if tgt is not None:
            if not isinstance(tgt, dict) or tgt.get("activityId") not in activities:
                err("qualification %s has a studyTarget pointing at an unknown activity" % qid)
        if scope == "activity" and qid not in granted:
            err("qualification %s has scope 'activity' but no activity grants it" % qid)
        if scope == "lesson" and qid not in lesson_granted:
            err("qualification %s has scope 'lesson' but no lesson completionPolicy grants it" % qid)
        if scope in ("unit", "course"):
            # §7 still holds: nothing can prove these yet, so nothing may grant them.
            err("qualification %s has scope %r — unit/course completion is not authoritative yet, so "
                "such a qualification cannot be earned" % (qid, scope))
    return errs


def load_data(path=_PATH):
    """Parse the registry file. Returns (data, errors); a duplicate key or bad JSON is an error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f, object_pairs_hook=_no_dup_keys), []
    except Exception as e:
        return {}, ["cannot load %s: %s" % (path, e)]


DATA, LOAD_ERRORS = load_data()
REGISTRY = Registry(DATA)
