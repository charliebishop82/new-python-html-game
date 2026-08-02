# Full Code Review

Reviewed: 2026-08-02

Scope: the complete generated `game/` application, including Python modules,
templates, routes, queue handlers, SQL/schema references, setup, and admin flow.

No application files were changed during this review.

## Resolution status

Resolved on 2026-08-02:

- Authentication exemptions now include login and registration POST endpoints.
- Authenticated players are loaded in `before_request` before route handlers run.
- Nested transactions now use SQLite savepoints while preserving the queue's
  outer all-or-nothing transaction.
- New accounts use a nullable `class_id` until character creation.
- The admin app now resolves templates from the correct template root.
- Post-combat kill/reset and zero-credit XP writes have explicit transaction
  boundaries.
- Setup recognizes both supplied workbook filename variants.
- Protagonist fallback awards now use explicit transactions.
- Relevant phase source files were updated so regeneration preserves the core
  fixes.

Validation completed:

- Python syntax passed for all generated modules.
- Fresh schema creation and nullable-class registration passed with foreign keys
  enabled.
- Nested savepoint commit and rollback behavior passed.
- A fresh ingestion run preserved the authentication, schema, admin, and setup
  corrections.

## P0 — Launch blockers

### 1. Login and registration POST requests are blocked

- File: `game/app.py`
- Lines: 17–18

`_AUTH_EXEMPT` includes `auth.login` and `auth.register`, which are the GET
endpoint names. The POST handlers have the endpoint names `auth.login_post` and
`auth.register_post`. An unauthenticated form submission is therefore redirected
to the login page before its handler can execute.

Recommended fix: add both POST endpoint names to `_AUTH_EXEMPT`.

### 2. `g.player` is loaded too late

- File: `game/app.py`
- Lines: 55–64

The player is loaded by a template context processor. Routes such as
`dashboard.index()` access `g.player` before template rendering begins, so the
value has not been created yet and authenticated pages can raise an
`AttributeError`.

Recommended fix: load the authenticated player in a `before_request` function.
The context processor should only expose the already-loaded player to templates.

### 3. Queued actions nest exclusive transactions

- File: `game/queue_handler.py`
- Lines: 44–47

`enqueue_and_process()` invokes every registered handler inside
`exclusive_transaction()`. The handlers also open their own
`exclusive_transaction()` blocks. SQLite does not allow `BEGIN EXCLUSIVE` inside
an active transaction, so common actions can fail with:

`cannot start a transaction within a transaction`

Affected workflows include tavern, shop, blacksmith, equipment, level-up, combat,
and post-combat resolution.

Recommended fix: establish one consistent transaction owner. The simplest design
is generally to let each handler own its transaction while the queue wrapper
maintains its receipt/status transactions separately.

### 4. Registration inserts an invalid class foreign key

- File: `game/routes/auth.py`
- Lines: 111–124
- Related schema: `game/schema.sql`, line 16

Registration inserts `class_id = 0`, but `players.class_id` is a non-null foreign
key referencing `classes(id)`. Foreign-key enforcement is enabled, and normal
autoincremented class IDs begin at 1. Registration will fail unless an artificial
class row with ID 0 exists.

Recommended fix: either make `class_id` nullable until character creation or use
a valid, explicitly created placeholder class.

## P1 — Major runtime problems

### 5. Admin templates resolve from the wrong template root

- File: `game/admin.py`
- Lines: 27–29

The admin application uses `template_folder="templates/admin"` but renders names
such as `admin/dashboard.html`. Flask will look for
`templates/admin/admin/dashboard.html`, which does not exist.

Recommended fix: use `template_folder="templates"`, or remove the `admin/` prefix
from all admin `render_template()` calls.

### 6. Post-combat writes escape transaction boundaries

- File: `game/combat/actions.py`
- Lines: 1077–1103
- Additional occurrence: line 1161

Boss/minion kill-count and instance-reset writes execute outside an explicit
transaction. They are immediately followed by `_award_drops()`, which opens its
own transactions. The zero-credit XP award also executes outside a transaction.
After the queue transaction problem is corrected, these operations can be rolled
back at teardown, conflict with a later transaction, or leave combat resolution
partially applied.

Recommended fix: group each logically atomic part of combat finalization inside a
clear transaction boundary and ensure helpers do not start nested transactions.

### 7. Setup expects the wrong workbook filename

- File: `game/setup.py`
- Lines: 12–16

Setup expects `GameContent_Filled.xlsx`, but the supplied workbook is named
`GameContent Filled.xlsx`. Setup will claim content is missing and skip the
initial import.

Recommended fix: align the configured filename with the supplied workbook or
safely discover the intended `.xlsx` file.

## P2 — Additional transaction issue

### 8. Protagonist-event fallback writes lack a transaction

- File: `game/routes/actions.py`
- Lines: 719–729 and 756–760

The no-movie and missing-item credit fallbacks call `execute_write()` without an
explicit `exclusive_transaction()` block. These writes may not commit reliably
once transaction ownership is repaired elsewhere.

Recommended fix: execute each fallback award and related feed entry in one
transaction.

## Checks that passed

- All 24 Python files parse successfully.
- No missing `config_defaults` constants were found.
- Every enqueued action name has a registered handler.
- Blueprint endpoint references resolve.
- Normal template references exist on disk.
- Static SQL statements prepare successfully against a fresh schema.
- The reconstructed schema creates 26 tables successfully.
- No unknown SQL table references were found.

## Verification limitation

A live Flask boot and request test was not run because Flask, APScheduler, and
Jinja were not installed in the available review runtime. The findings above are
based on direct control-flow inspection and SQLite behavior and do not depend on
the unavailable live test.
