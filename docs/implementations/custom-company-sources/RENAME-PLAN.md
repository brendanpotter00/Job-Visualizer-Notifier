# Renaming a tracked board — design

**Status:** implemented. Written before the code, so the reasoning is in the commit and
not only in the diff.

## The problem

A private board's `display_name` is DERIVED from the URL the user pasted
(`routers/user_companies._discovery_display_name`). It is a good guess and it is
sometimes wrong — `ycombinator.com/companies/raindrop/jobs` used to be stored as
"Ycombinator", and even after the directory-tenant fix a host-derived label reads like
`Janestreet` or `Jobs`. The owner wants to fix the label himself.

The endpoint is trivial. The trap is not.

## The trap: re-discovery overwrites the name

`display_name` is not written once at add time. Grepping every write to
`companies.display_name` on the custom-company path (there are four, and the two that
matter are UPDATEs):

| # | site | statement | when it runs |
|---|---|---|---|
| 1 | `custom_companies_service.add_custom_company` | `INSERT` | first add of an **ATS** board |
| 2 | `custom_companies_service.add_discovering_placeholder` | `INSERT` | first add of a **discovered** board (the 202 placeholder) |
| 3 | `custom_companies_service._promote_to_tracked` | `UPDATE … SET display_name = %s` | **every time discovery ACCEPTS a board** — reached from `add_discovered_company`, i.e. the discovery task, i.e. any re-discovery |
| 4 | `custom_companies_service.restart_refused_discovery` | `UPDATE … SET display_name = %s` | **the retry of a refused board** (`d27379e`), i.e. a re-add of a URL we previously refused |

3 and 4 are the clobbers. 4 is the loudest: its own docstring says

> THE DISPLAY NAME IS REFRESHED with the caller's freshly derived one. … there is no
> rename endpoint, so leaving it would make the retry the one moment we could fix it
> and did not.

That reasoning was right when there was no rename. The moment there is one, both
UPDATEs will silently undo a user's rename — 4 on the next re-add of a refused board,
3 when that retry then succeeds. A rename that a re-add reverts is worse than no
rename at all.

(For completeness, the writes that are NOT on this path and are not touched:
`users.display_name` and `feedback.display_name` are different tables; the ~30 Alembic
seed migrations write `visibility='public'` rows, which this endpoint refuses to touch.
`record_discovery_progress`, `record_first_scan`, `record_discovery_refusal`,
`published_board_match.store_suggestion`/`_mark_compared` and
`claim_custom_companies.push_next_run_at` all UPDATE `companies` but none of them names
`display_name`.)

## Decision: a second column, not a flag

Two candidate models:

| model | how a write site behaves | failure mode |
|---|---|---|
| **(a)** `display_name_is_custom BOOLEAN` | every existing write must add `display_name = CASE WHEN display_name_is_custom THEN display_name ELSE %s END` | **a new write site that forgets the guard silently clobbers.** Also destroys the derived name, so "reset to the suggested name" becomes impossible |
| **(b)** `user_display_name TEXT NULL` beside the derived one | every existing write is **unchanged**; readers resolve `COALESCE(user_display_name, display_name)` | a new READ site that forgets the COALESCE shows a stale-looking name. Cosmetic, and visible immediately |

**We take (b).** The property that decides it: with (b) the clobber is impossible *by
construction* rather than by remembering. Sites 1–4 keep writing the derived name into
the column they always wrote, and none of them can reach the user's name because the
user's name is not in that column. Forgetting a guard is the exact bug class the brief
warns about, and (b) has no guard to forget.

Two bonuses fall out: the derived name survives, so a "reset to suggested" affordance
is free later; and re-discovery keeps refreshing the derived name (useful — if the user
ever clears their override, they get the *current* derivation, not the one from the day
they added the board).

The cost of (b) is that the READ side has one new rule. It is confined to one string:

```python
# custom_companies_service.py
EFFECTIVE_DISPLAY_NAME_SQL = "COALESCE(c.user_display_name, c.display_name)"
```

used `AS display_name` in exactly the three owner-facing SELECTs, so every caller's row
dict already carries the effective name and no Python-side resolution exists to skip:

* `list_owned_companies` — the My Companies list
* `find_owned_company_by_source_key` — the idempotent re-add response
* `get_company_if_owner` — the ownership read behind the jobs route (and now rename)

The two UPDATEs (3 and 4) additionally gain
`RETURNING COALESCE(user_display_name, display_name) AS display_name`, because both
build their return dict from the *freshly derived* name they just wrote. Without the
RETURNING the database would be correct and the response body would still show the
derived name for one render — a rename that "appears to revert". Reading it back in the
same statement means the row and the response can never disagree.

**Admin views are deliberately left on the derived name**
(`custom_companies_admin`, `custom_company_integrity`). Those pages triage *boards*,
and the URL-derived label is the stable identifier there; the ownerless-board report
has no owner whose name to prefer. Noted as a decision, not an oversight.

## Migration

`companies.user_display_name TEXT NULL`. Nullable with no default ⇒ a catalog-only
`ALTER TABLE` on PG 11+, no table rewrite and no long lock — the same rule the E7
Phase-1 migration (`fb8467065dfc`) documents for the seven columns it added, and the
reason `docs/incidents/2026-04-18-migration-filled-postgres-volume/` exists.
Autogenerated from `db_models.py` per `src/backend/CLAUDE.md`, `down_revision =
b4d17c2a9e51`, so the tree keeps a single head. Prod is stamped `1d2d6c17acfc`, which
is an ancestor, so it picks this up in the normal chain.

## The endpoint

```
PATCH /api/users/companies/{company_id}
  body     {"displayName": "Raindrop"}
  200      UserCompanyResponse   (the full row, same shape the list returns)
  404      not yours / not found / not a private board
  422      {"reason": "...", "detail": "..."}   name_empty | name_too_long
  429      rename burst limit
  503      flag off
```

Conventions copied from its neighbours in `routers/user_companies.py`: `_require_flag()`
first, `get_current_user` + the `email` claim check, `get_user_by_email`, the machine-
readable `_reject(422, reason, detail)` body the frontend's `asAddFailure` requires, and
`to_camel` on the request/response models.

**Ownership is one SQL predicate, not a read-then-write.** The UPDATE carries its own
`EXISTS (SELECT 1 FROM user_companies …)` and `visibility = 'user'`, so there is no
window between the check and the write and no second code path that could be reached
with the check skipped. `rowcount == 0` covers all three of "not yours", "does not
exist" and "public board" and answers **404 "Company not found"** — the same answer, for
the same reason, that `DELETE /{company_id}` already gives a non-owner: the closest
sibling mutation, and it does not disclose whether the id exists.

### Validation

The name is rendered as a React text child, so it is HTML-escaped on render and the
threat is not injection. It is *layout* and *spoofing*:

1. `strip()` + collapse internal whitespace runs to single spaces.
2. Remove the NON-WHITESPACE C0/C1 controls and DEL, `U+200B`, `U+FEFF`, and the bidi
   marks/embeddings/overrides/isolates (`U+200E`/`U+200F`, `U+202A`–`U+202E`,
   `U+2066`–`U+2069`). Stripping rather than rejecting: an invisible character is not
   something a user can act on an error message about, and a bidi override in a company
   label has no legitimate use. That last group is what stops `"Acme‮…"` reordering
   itself on the card.

   **The whitespace controls are deliberately NOT in that set** — tab, newline, the C0/C1
   separators, NEL, `U+2028`/`U+2029`. Deleting a tab turns `"Acme\tCorp"` into
   `"AcmeCorp"`; leaving it lets step 1's `str.split()` treat it as the word break it
   obviously is and produce `"Acme Corp"`. (A first draft got this wrong and the smoke
   check caught it.) `U+200C`/`U+200D` are left alone too: ZWJ/ZWNJ are load-bearing in
   Persian, several Indic scripts and emoji sequences, so stripping them would corrupt
   real names to defend against nothing.
3. Empty after all that ⇒ 422 `name_empty`.
4. Longer than **100** characters after all that ⇒ 422 `name_too_long`. 100 is not a
   new number: it is the cap `UserUpdateRequest.display_name` and `AccountPage`'s
   `maxLength` already use for the other display name in this product, and a second
   limit for the same kind of field is a thing that drifts. Pydantic keeps a loose
   `max_length` ceiling far above it purely to bound the payload; the 100 is enforced
   in the router so the response carries a `reason` the UI can map to copy (a Pydantic
   `Field` violation returns Pydantic's own 422 shape, which has no `reason`, and
   `asAddFailure` — which hard-checks `status === 422` *and* a string `reason` — would
   fall through to generic copy).

**Empty is rejected, not a revert.** Clearing the box is much more likely a mistake than
a request to go back to "Ycombinator", and the UI's Cancel is the affordance for
"never mind". The column supports a revert (`SET user_display_name = NULL`) if that is
ever wanted; it is deliberately not reachable from this endpoint today.

### Rate limit

A rename is one UPDATE. It starts no browser, makes no outbound request and spends no
LLM call, so it must **not** consume either of the ADD path's budgets: not the 10/60s
burst limiter (that one exists to bound Chromium sessions) and emphatically not the
20/month cap (that one is the spend guard — charging a slot for fixing a typo would be
absurd, and the cap is defined as "URLs we acted on", which a rename is not).

It is still not free — it is an authenticated write — so it gets its own
`SlidingWindowRateLimiter` at **30/60s per user**, the same in-process shape as the
other three. 30/min is an order of magnitude above any human editing rate and bounds a
replayed token to a harmless trickle.

## Frontend

* `renameUserCompany` mutation in `features/userCompanies/userCompaniesApi.ts`,
  invalidating the same list tag `addUserCompany`/`removeUserCompany` already
  invalidate — one tag, so the list refreshes exactly once.
* Inline edit **in the card**: the name becomes a `TextField`, Enter commits, Escape
  cancels, focus returns to the trigger button on cancel/commit. A pending state
  (disabled field + spinner) rather than an optimistic patch: the brief's failure mode
  is "appears to succeed then silently reverts", and not claiming success until the
  server agrees makes that unreachable.
* Errors map off the 422 `reason` the same way the add path's failures do.
* The name truncates (`noWrap` + `textOverflow`) so a long name cannot widen the card.

## Card polish (tightening, not redesign)

Same card, same components, same information. Four changes, all of them tightening:

| What | Before | After | Why |
|---|---|---|---|
| **Alignment** | actions vertically centred against the whole left column | top-aligned, and the two buttons grouped with `flexShrink: 0` | the left column is two lines and the actions are one, so centring floated them against the gap and lined them up with nothing |
| **Wrapping** | left column sized by its content | `flexGrow: 1` beside the existing `minWidth: 0`, name wraps anywhere | `minWidth: 0` did nothing without a grow, so a long name pushed the buttons off the card. A user can now type the name, so "no spaces in it" stopped being hypothetical |
| **Hierarchy** | count was one of four identical `body2 text.secondary` phrases | count takes `text.primary` + weight 500 | it is the number people scan this list for, and finding it meant reading the whole line |
| **Spacing** | one uniform 8px gap both ways | column gap 1.5, row gap 0.25 | the metadata wraps to two lines at narrow widths, and at 8px the second line read as part of the first |

**The count is deliberately not two-toned** with a `<span>` around just the digits, which
is the obvious way to do it. Testing Library matches an element on its DIRECT text
children, so wrapping the number splits `"12 open jobs"` across two elements and every
`getByText(/12 open jobs/)` in the suite stops matching. Three existing tests failed on
exactly that; bending assertions about what the user reads to fit a styling choice is the
wrong trade, so the styling changed instead.
