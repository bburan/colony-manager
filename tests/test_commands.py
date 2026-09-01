"""Tests for the ``flask data`` CLI group (``commands.py``).

Exercises option parsing, the shared name/id resolver, and that each
subcommand runs end-to-end against the per-test DB. These don't assert
DB mutations (the underlying ``sync.py`` functions have their own
coverage) — they verify the CLI wiring that replaced the old
``scripts/sync_data.py``.
"""


def _run(app, *args):
    return app.test_cli_runner().invoke(args=['data', *args])


def test_sync_dry_run_ok(app, db_session):
    result = _run(app, 'sync', '--dry-run')
    assert result.exit_code == 0
    assert 'sync:' in result.output


def test_sync_rating_ok(app, db_session):
    result = _run(app, 'sync-rating')
    assert result.exit_code == 0
    assert 'sync-rating:' in result.output


def test_rehash_dry_run_ok(app, db_session):
    result = _run(app, 'rehash', '--dry-run')
    assert result.exit_code == 0
    assert 'rehash:' in result.output


def test_refresh_dry_run_runs_sync_then_skips_rating(app, db_session):
    result = _run(app, 'refresh', '--dry-run')
    assert result.exit_code == 0
    assert 'sync:' in result.output
    assert 'sync-rating: skipped (dry-run)' in result.output


def test_unknown_datatype_errors(app, db_session):
    result = _run(app, 'sync', '--datatype', 'No Such DataType')
    assert result.exit_code != 0
    assert 'DataType not found' in result.output


def test_rematch_requires_datatype(app, db_session):
    result = _run(app, 'rematch')
    assert result.exit_code != 0            # click usage error
    assert '--datatype' in result.output


def test_datatype_resolved_by_id_and_name(app, db_session):
    """A real DataType resolves via both its numeric id and its name."""
    from .factories import make_animal_data_type

    dt = make_animal_data_type(db_session, name='CLI Photos')
    db_session.commit()

    by_id = _run(app, 'sync', '--datatype', str(dt.id), '--dry-run')
    assert by_id.exit_code == 0
    by_name = _run(app, 'sync', '--datatype', 'CLI Photos', '--dry-run')
    assert by_name.exit_code == 0
