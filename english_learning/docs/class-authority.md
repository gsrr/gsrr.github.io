# Class membership and teacher authority (Phase 12B.1.2)

Phase 12B.2 set out to add an accessibility accommodation for Read Along and **stopped during its
authority audit**, because the question it had to answer first — *"may teacher X act on student
Y?"* — had no answer the server could give. This document records the repair.

## What was wrong

Three findings, all reproduced against the real server:

1. **A student account recorded no class membership at all.** A registered account was
   `{salt, hash, code, created}` and nothing more. There was no `joinedClass`, no `teacher`, no
   `memberOf` — no outward link of any kind.
2. **A "student" in a teacher's roster was a display-name string**, stored as
   `progress[teacher]["students"][name] = snapshot`. `'Jimmy'` was not an account; it was a key.
3. **`/api/class/sync` authenticated the class code only.** An unauthenticated client that knew a
   code could write arbitrary names into any teacher's dashboard. Demonstrated: `NotMyStudent` and
   `STUD_1` were injected into a teacher's roster with **no token at all**, response `200 {"ok":true}`.

So a roster was an attacker-controlled list, and any feature built on "the students in my class"
would have inherited that as a privilege-escalation path. Anyone who learned a class code could have
had an accommodation — or anything else — granted to a name they invented.

## The canonical membership source

Membership belongs to the **student's own account record**, and nowhere else:

```
db["users"][<studentAccount>]["joinedClass"]   = <class code>
db["users"][<studentAccount>]["joinedClassAt"] = <epoch seconds>
```

Ownership is derived through the existing code index — there is no second source of truth:

```
class code  --->  db["codes"][code]  --->  owning teacher account
```

```
teacher account
    | owns            db["users"][teacher]["code"], indexed by db["codes"]
    v
class code
    | membership      db["users"][student]["joinedClass"]   <-- the ONLY authority
    v
student account
    | contributes     progress[teacher]["members"][student]["progress"]
    v
progress snapshot
```

Every edge is server-derived. The client contributes exactly one thing: the code the learner typed,
which is validated against the index. No client field decides who joined.

## Why display names are not authority

A display name is presentation. Two learners may legitimately both be "Jimmy"; a learner may rename
themselves at any time; and a name can simply be invented. None of those may affect identity, so the
roster is keyed by **account** and the name is carried alongside as a label:

```
progress[teacher]["members"][<studentAccount>] = {
    displayName: <label, presentation only>,
    joinedAt:    <epoch seconds>,
    progress:    <that account's own snapshot>
}
```

Renaming updates the label only. It cannot create a second identity, move membership, or change who
may manage whom.

## Role audit: there is no account "type" (Phase 12B.1.2R)

Before accepting `may_manage()` as an authorization boundary, the account model was audited for an
authoritative role. **There is none**, measured rather than assumed:

| question | answer |
| --- | --- |
| is teacher/student recorded as account state? | **No.** No `role`, `kind`, `type`, `isTeacher` or `isStudent` field exists, and there is no `is_student()` / `is_teacher()` / `role_of()` anywhere on the server. |
| does `/api/register` differ from `/api/student/register`? | **No.** Both dispatch to the same `_handle_auth`, and a freshly registered account is `{code, created, hash, salt}` either way — structurally identical, byte-for-byte the same field set. |
| can the server prove `is_student(a)` / `is_teacher(a)` independently of `joinedClass`? | **No.** |
| are both roles intentionally valid for one account? | **Yes.** Every account owns a class code (so it can act as a teacher) and can join another class (so it can act as a member). The product's own role screen asks *"Who's using the app?"* — an entry choice, not an account property. |
| does any workflow depend on a teacher account joining a class? | **No.** The join control exists only on the student-side My Progress screen; the teacher panel has no join UI. |

Because no authoritative role exists, **this phase did not invent one.** Manufacturing a `role` field
here would have meant inferring it from which button a user pressed — exactly the kind of
client-supplied claim this repair exists to stop. The model stays relationship-based, and the
following section defines precisely what that does and does not mean.

## Four different concepts

These are routinely conflated, and conflating them is what produced the original exploit:

| concept | what it is | authoritative? |
| --- | --- | --- |
| **account identity** | the key in `db["users"]`, established by a token | **yes** — the only identity |
| **class membership** | `db["users"][account]["joinedClass"]` | **yes** — the only membership |
| **display label** | `members[account].displayName`, chosen by the account | no — presentation only |
| **management authority** | the `may_manage()` relation, derived from the two authoritative facts above | **yes** — derived, never stored as a grant |

A roster row is a *view* built from membership plus a label. It is not identity and not authority.

## The canonical authorization helper

One function answers the authority question, and Phase 12B.2 must reuse it rather than compare code
strings itself:

```python
may_manage(teacher_account, student_account, db=None) -> bool
```

It derives its answer solely from account state:

- both accounts must exist;
- the student's own `joinedClass` must resolve, through `db["codes"]`, to that teacher;
- **`teacher == student` is always False.** Teachers and students share one namespace and *every*
  account owns a class code, so an account could otherwise join its own class and become its own
  manager. For an accessibility accommodation that would be self-service authorization — exactly
  what must never be possible.

Supporting derivations: `class_owner_of(db, code)` (returns `None` for an unknown code *or* a
dangling index entry) and `class_members_of(teacher)` (re-derives the member list through
`may_manage`, so a stored roster copy can never grant authority on its own).

### What `may_manage(teacher, student)` means — and does not mean

**It means:** *the first account owns the class that the second account voluntarily joined, and they
are not the same account.* Nothing more.

**It does not mean** any of the following, and no caller may assume them:

- that the target has an intrinsic "student account type" — **no such type exists** (see the role
  audit above). The parameter is named `student` for the relationship it describes, never for a
  property of the account;
- that the target is not itself a teacher elsewhere. Any account may own a class *and* be a member of
  another; an account that joins a class becomes manageable by that class's owner **by its own
  authenticated choice**;
- that co-members can manage one another. Sharing a class grants a member authority over **nobody**;
- that authority can be inferred from an account type, a display name, roster contents, or possession
  of a class code. None of those is authority.

**Consequences Phase 12B.2 must honour:**

- accommodation changes may be authorized **only** through `may_manage()`;
- no accommodation API may infer authority from account type, display name, roster contents or class
  code;
- self-management stays forbidden, so an account can never grant itself an accommodation;
- joining a class grants the joining account authority over no one.

### Class-switch partial failure

A move writes the account record first, then adjusts the roster copies. If persistence failed between
those steps the roster would be cosmetically stale — and that is harmless, because **authority is
re-derived from `joinedClass` on every call**. Measured: with `joinedClass` moved to teacher B but an
orphaned `members["S"]` row left behind in teacher A's file, `may_manage(A, S)` is `False`,
`may_manage(B, S)` is `True`, and A's dashboard does not list S. No transaction framework is needed,
and none was built; the invariant is pinned by test instead.

## Authentication requirements for class sync

`POST /api/class/sync`

| | before | after |
| --- | --- | --- |
| token | not required | **required**; `401 auth_required` without one |
| who joins | names in the body | the account the **token** resolves to |
| class code | treated as authority | validated against the code index; `404 bad_class_code` if unknown or dangling |
| own code | accepted | `400 self_class` |
| body `students` | written verbatim as roster keys | **ignored entirely** |
| body `account` / `user` | n/a | **ignored**; the token decides |
| roster key | display name | student account |

The response reports what the server decided: `{ok, joinedClass, account}`.

## Legacy roster data

Pre-phase `students` entries are **kept and never reinterpreted**. They cannot be bound to an account
— matching a name string to an account would be a guess, and a wrong guess would hand a stranger
authority over a learner — so they stay explicitly non-authoritative:

- the dashboard returns them under `students` with `legacyStudents: true`, separately from `members`;
- the teacher UI shows them below the authoritative list under *"Earlier records (not linked to an
  account)"*, stating that they confer no management authority;
- `may_manage()` returns False for them, and they are never promoted into `db["users"]`.

No teacher loses history; no history becomes authority.

## Membership changes

The smallest semantics compatible with the product:

- **first join** — records `joinedClass` + `joinedClassAt`, adds the account to the roster;
- **rejoining the same class** — idempotent: one roster identity, original `joinedAt` preserved,
  label refreshed;
- **changing class** — authoritative the moment the account record changes. The previous teacher's
  roster row is removed, so the old teacher loses both the listing and `may_manage` authority, and
  the new teacher gains both. No duplicated membership;
- **leaving without joining another class** — not currently a product action, so none was invented;
- **class deletion** — not a product action either. A dangling code resolves to `None`, so authority
  fails closed rather than transferring.

The teacher's own-device `POST /api/sync` still writes only the legacy name-keyed bucket. It cannot
create an authoritative member, which is asserted by test.

## Security properties now guaranteed

1. An unauthenticated class-sync is refused `401` with **zero** mutation to accounts or roster.
2. Empty, forged and unknown tokens fail closed.
3. The joining account is decided by the token; `account`/`user`/`students` body fields are ignored.
4. No account can join, move or impersonate another account.
5. No teacher can acquire authority over another teacher's student by naming them.
6. Accounts sharing a display name remain distinct identities.
7. Renaming cannot change identity, membership or authority, nor duplicate a roster row.
8. An unknown code, a learner's own code and a dangling code index entry are all refused.
9. A class move transfers authority in both directions with no duplication.
10. Legacy name-keyed rows confer no authority and are never promoted to accounts.
11. Self-management is impossible.
12. The dashboard exposes no salt, password hash or token; membership does not appear in another
    learner's dashboard, the leaderboard or the learning state.

## Remaining limitations

- **Any account may join any class.** Accounts are one namespace, so a teacher can join a
  colleague's class and become manageable by them. That is the learner's own authenticated choice,
  not an escalation, but it means "teacher" and "student" remain *roles in a relationship* rather
  than account types.
- **Knowing a class code still lets an authenticated account join.** A code is an invitation, not a
  secret; there is no approval step. A teacher who needs to control entry has no mechanism yet.
- **No leave/remove action.** A learner can only move to another class, and a teacher cannot evict.
- **Legacy rows stay unbound for ever.** They are inert, but they will keep appearing in dashboards
  until a teacher's data is cleared.
- **Progress snapshots remain client-supplied** for the learner's own account. This phase fixed
  *identity*, not snapshot integrity: an account can still upload whatever local numbers it likes
  about itself. Authoritative learning progress is unaffected — it lives in the learning domain, not
  in this roster.

## What this unblocks

`may_manage()` is now the single, provable authority relation Phase 12B.2 needs. That phase remains
**not implemented**: no accommodation flag, no typed Read Along, no management endpoint and no
educator control exists yet.
