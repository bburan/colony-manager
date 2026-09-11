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


def test_prune_defaults_to_reporting_only(app, db_session):
    """Unlike the other subcommands, prune needs --apply to write."""
    result = _run(app, 'prune')
    assert result.exit_code == 0
    assert 'prune:' in result.output


def test_prune_apply_ok(app, db_session):
    result = _run(app, 'prune', '--apply')
    assert result.exit_code == 0
    assert 'prune:' in result.output


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


def test_prune_apply_explains_rows_whose_file_is_absent(
    app, db_session, tmp_path, monkeypatch,
):
    """``absent=N`` with ``--apply`` reads as a bug without an explanation.

    Prune deliberately never deletes a row whose file is gone -- the share
    may just be unmounted -- so the output has to say that, and where
    those rows do get dealt with.
    """
    from colony_manager.datatypes import reset_registry_cache
    from colony_manager.enums import DataStatus
    from colony_manager.models import AnimalData
    from .factories import make_animal_data_type, make_data_location

    monkeypatch.setenv(
        'COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes',
    )
    reset_registry_cache()
    dtype = make_animal_data_type(db_session, name='CLI Absent')
    dtype.description_class = 'fake_animal'
    db_session.commit()
    location = make_data_location(db_session, datatype=dtype, base_path=tmp_path)
    db_session.add(AnimalData(
        datatype_id=dtype.id, location_id=location.id,
        relative_path='never-written.txt', name='never-written.txt',
        status=DataStatus.UNREVIEWED,
    ))
    db_session.commit()

    result = _run(app, 'prune', '--apply', '--datatype', str(dtype.id))
    reset_registry_cache()
    assert result.exit_code == 0
    assert 'absent=1' in result.output
    assert '1 row(s) left alone' in result.output
    assert 'flask data sync' in result.output


def test_verbose_survives_logging_configured_elsewhere():
    """-v used to ride on basicConfig, which no-ops once root has a handler.

    A description-class dependency configuring logging on import was
    enough to silently turn the flag off.
    """
    import logging
    from colony_manager_gui.commands import _enable_info_logging

    pkg = logging.getLogger('colony_manager_gui')
    prior_level, prior_handlers = pkg.level, list(pkg.handlers)
    root_handler = logging.StreamHandler()
    logging.root.addHandler(root_handler)
    try:
        pkg.setLevel(logging.WARNING)
        _enable_info_logging(True)
        assert logging.getLogger('colony_manager_gui.sync').isEnabledFor(
            logging.INFO)
        # Root already prints what propagates to it; a second handler here
        # would double every line.
        assert pkg.handlers == prior_handlers
    finally:
        logging.root.removeHandler(root_handler)
        pkg.setLevel(prior_level)
        pkg.handlers[:] = prior_handlers


def test_verbose_adds_a_handler_when_nothing_is_configured(monkeypatch):
    """With no handler anywhere, raising the level alone would print nothing."""
    import logging
    from colony_manager_gui.commands import _enable_info_logging

    pkg = logging.getLogger('colony_manager_gui')
    prior_level, prior_handlers = pkg.level, list(pkg.handlers)
    monkeypatch.setattr(logging.root, 'handlers', [])
    pkg.handlers[:] = []
    try:
        _enable_info_logging(True)
        assert len(pkg.handlers) == 1
    finally:
        pkg.setLevel(prior_level)
        pkg.handlers[:] = prior_handlers
