# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the app

```sh
export SECRET_KEY=dev
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/colony_manager
flask --app colony_manager_gui:create_app run
```

`REDIS_URL` is optional — if unset, background jobs (sync/rematch) fall back to fakeredis and run inline in the request thread (see "Background jobs" below). `COLONY_MANAGER_DESCRIPTION_REGISTRY` is required for any data-file sync/upload features to work (see "Description-class plugin system" below); the rest of the app runs without it.

No frontend build step — Bootstrap 5, Font Awesome, htmx, Alpine.js, and Plotly are all loaded via CDN `<script>`/`<link>` tags in `templates/base.html`. Editing a template or `static/js/app.js` takes effect on next request; no bundler.

### Tests

```sh
pytest                       # all tests
pytest tests/test_models_animal.py    # one file
pytest tests/test_models_animal.py::test_age_display_units   # one test
pytest -k terminate          # by keyword
pytest -n auto               # parallel, one worker per CPU
```

Two tiers:
- **Unit** (helpers, escaping, safe-url, decorators) — runs anywhere, no DB.
- **Integration** (models, routes, sync) — needs `TEST_DATABASE_URL` pointing at a Postgres cluster the role can `CREATEDB` on. Each test run clones a per-worker template DB (built once via `alembic upgrade head`) into a throwaway DB. Without `TEST_DATABASE_URL` set, integration tests are **skipped**, not failed.

Full setup instructions, troubleshooting, and the `TEST_DB_PREFIX`/`TEST_KEEP_DBS` env vars are in `tests/README.md` — read it before debugging a fixture/DB issue rather than re-deriving from `tests/db_fixtures.py`.

On this machine, the `colony-manager-test` conda env already has `TEST_DATABASE_URL` configured (points at a remote Postgres instance). Activate it before running the integration tier:

```sh
source /c/Users/buran/bin/anaconda3/etc/profile.d/conda.sh && conda activate colony-manager-test
```

Tests use SQLAlchemy 2.0 style exclusively (`select(...)`, `session.scalars(...)`) — no `Model.query`.

### Migrations

```sh
export DATABASE_URL=postgresql+psycopg2://...
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Background worker / CLI

```sh
python -m colony_manager_gui.worker          # RQ worker (needs REDIS_URL; won't fork on native Windows — use WSL/Docker)

# All data-file ops live under the `flask data` group (see commands.py):
flask --app colony_manager_gui:create_app data sync         [--datatype NAME|ID] [--dry-run] [-v]
flask --app colony_manager_gui:create_app data rematch      --datatype NAME|ID [--force] [--dry-run]
flask --app colony_manager_gui:create_app data rehash       [--dry-run]
flask --app colony_manager_gui:create_app data sync-rating  [--datatype NAME|ID] [-v]
flask --app colony_manager_gui:create_app data refresh      [--datatype NAME|ID]   # sync + sync-rating; the cron entrypoint
```

There is no standalone sync script — `flask data <cmd>` is the only CLI surface. Nothing runs these on a schedule; a nightly refresh must be wired via cron/systemd (or rq-scheduler, see `docs/jobs.md`) calling `flask data refresh`.

## Architecture

### Two-package split

- **`colony_manager`** (`src/colony_manager/`) — framework-agnostic core: SQLAlchemy models (`models/`), the description-class plugin system (`datatypes.py`), a standalone scoped session (`db.py`). No Flask dependency; importable from scripts/notebooks.
- **`colony_manager_gui`** (`src/colony_manager_gui/`) — the Flask app: `routes/`, `forms/`, `services/`, `templates/`, plus `jobs.py`/`sync.py`/`worker.py` for background processing. Depends on `colony_manager`, never the reverse.

### Database session

There is no Flask-SQLAlchemy. `colony_manager.db.get_session()` returns one process-wide `scoped_session` bound to `DATABASE_URL`, read lazily on first use (not at import) so tests can rebind it per-test via `monkeypatch`. `colony_manager_gui/__init__.py` exposes a `db` proxy object whose `.session` property forwards to that same scoped session, so routes, the RQ worker, and standalone scripts all share one session-management story. `routes/util.py:get_or_404` is the standalone replacement for Flask-SQLAlchemy's `get_or_404` sugar — use it instead of `session.get(...)` + manual 404.

### Models

`colony_manager/models/` splits by domain (`base.py` infra + association tables, `system.py` users/jobs, `animal.py` the core colony domain, `histology.py`, `data.py`), all re-exported from `models/__init__.py`. Every domain model extends the abstract `VersionedModel` (in `base.py`) — despite the name, this is **not** row versioning (that used to be `sqlalchemy_continuum`, removed in migration `e5a7c9b1d3f2`); today it only supplies the `__tablename__` auto-derivation convention. Cross-module relationships use string references and `orm.configure_mappers()` at the end of `models/__init__.py` to avoid import-order circular dependencies — new model modules should only import from `base.py`, not each other.

`DataType`/`Data` are polymorphic hierarchies (`polymorphic_on=target_type`) with one subclass pair per attachable entity (`AnimalEventData`/`AnimalEventDataType`, `ConfocalImageData`/`ConfocalImageDataType`, etc.) — see `models/data.py`. Extending to a new attachable entity means adding a subclass pair there, not branching on `target_type` strings elsewhere.

### Routes/forms/services triad

Each domain (`animals`, `cages`, `breeding`, `histology`, `studies`, `auth`, `data_files`, `main`) has a Flask blueprint in `routes/`, a matching `forms/<domain>.py`, and — where a route needs a non-trivial filtered query — a `services/<domain>_queries.py`. Follow this split for new features rather than putting query logic inline in a route.

`routes/util.py` defines the shared shape every mutation route follows: build a `FlaskForm`, `render_modal(form, ...)` to show it (HTMX GET → modal body), then on submit either `htmx_or_redirect(...)` (success: partial re-render for HTMX, flash+redirect otherwise) or `htmx_error(...)` (failure: HTMX error alert + `HX-Retarget`, flash+redirect otherwise). `is_htmx()` checks the `HX-Request` header. New CRUD routes should reuse these helpers rather than hand-rolling the HTMX/non-HTMX branching.

A form editing only *some* of a model's fields (e.g. just `custom_id`) can be POSTed straight at the same route/handler that a full edit form uses, by constructing the full form bound to `obj=<the row>` — WTForms falls back to the object's current attribute for any field absent from the submitted data, so only the submitted fields actually change. This only works when every field on the form corresponds to a real column/relationship on the object; forms that mix in creation-only fields (e.g. `CageForm`'s `sex`/`dob`/`number_of_animals`, used only to spin up a cage's first animals) can't be reused this way for editing — see `CageDetailsForm` vs `CageForm` in `forms/cages.py` for the two patterns side by side.

### Auth

Flask-Login gates every route by default via a global `before_request` hook (`check_login` in `colony_manager_gui/__init__.py`). Routes that must stay reachable while logged out opt out with the `@public` decorator (`auth_decorators.py`) rather than a maintained string allowlist. `User.is_admin()` (an `admin` boolean column) gates `/settings/*` in `routes/main.py`'s `before_request`.

### Session-scoped UI state

A couple of nav-bar dropdowns (active species filter, default age-display unit) are stored in the Flask session and injected into every template via the `inject_global_vars` context processor in `colony_manager_gui/__init__.py`, rather than being passed explicitly by each route. Templates read `species`/`selected_species`/`age_unit` as ambient globals; a route only needs to pass them explicitly when overriding per-page (see how `animals.html`/`cages.html`'s own age-unit filter buttons shadow the session default).

### Background jobs (RQ)

Sync/rematch runs are queued through RQ (`app.rq_queue`, wired in `_configure_rq`). With `REDIS_URL` set, jobs run in a separate worker process (`worker.py`); unset, the app falls back to fakeredis with `is_async=False` and jobs run inline — this is also how the test suite exercises job code with no Redis/worker needed. Job state lives in the `SyncJob` table (`pending → running → success|failed`); a boot-time sweep in `worker.py` fails any row whose RQ counterpart vanished (worker killed mid-job). Full architecture, recovery, and scaling notes: `docs/jobs.md`.

### Description-class plugin system

`DataType.description_class` stores a short opaque key, not an import path (closes an RCE vector where an admin-controlled DB column used to be `importlib.import_module`'d directly). The host deployment points `COLONY_MANAGER_DESCRIPTION_REGISTRY` at a module exposing a `DESCRIPTION_CLASSES = {key: DataTypeDescription subclass}` dict; `colony_manager/datatypes.py:load_description_class` resolves keys through it. A `DataTypeDescription` subclass implements `parse()` (extract metadata from a file/folder) and `hash_files()` (dedup/change detection), and optionally opts into `@plot_callback`/`@pdf_callback` visualizations and upload-from-UI support (defining `upload_filename` — its mere presence is the opt-in signal `is_upload_capable` checks for). `sync.py:sync_locations` is the on-disk-walk ingestion path; `services/uploads.py:handle_upload` is the inverse (UI-driven upload) path — see `docs/uploads.md` for the full upload pipeline and how to extend it to a new attachable entity type.

`colony_manager` itself ships no description classes — `mmm_db` (the `mmm_db.registry` example in `docs/jobs.md`) is not a placeholder name, it's a real sibling repo on this machine: `../mmm-db` (i.e. `C:/Users/buran/projects/colony-manager/src/mmm-db`), installed editable into at least the `gerbil-manager` conda env. Its `src/mmm_db/registry.py` is the actual `DESCRIPTION_CLASSES` dict, with real subclasses in `abtsdata.py`/`cftsdata.py`/`images.py`/`photos.py`. If a task involves a specific data type (ABR, DPOAE, synaptogram counts, etc.) or debugging sync/matching behavior for one, the implementation lives there, not in this repo.

## Conventions

- `Animal.sex` is stored as lowercase `'male'`/`'female'`, not `'M'`/`'F'`.
- Enums (`colony_manager/enums.py`) are `StrEnum` — they compare equal to their string values, so DB columns, `==`, and template rendering all work without `.value`.
- SQLAlchemy 2.0 style throughout (`select(...)`, `session.scalars(...)`) — no `Model.query`, in app code or tests.
