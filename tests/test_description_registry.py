"""Regression tests for the description-class registry shipped in PR2.

The old code passed the admin-controlled ``DataType.description_class``
column straight to ``importlib.import_module``, so any importable
module on PYTHONPATH could be loaded by writing the right string into
the DB. PR2 replaced that with an explicit allow-list keyed by short
identifier.
"""
import pytest

from colony_manager.datatypes import DataTypeDescription


class _Stub(DataTypeDescription):
    def parse(self):
        return None

    def hash_files(self):
        return []


@pytest.fixture
def fake_registry(monkeypatch):
    """Inject a synthetic registry module via env var + sys.modules."""
    import sys
    import types

    module = types.ModuleType('_test_registry')
    module.DESCRIPTION_CLASSES = {'STUB': _Stub}
    sys.modules['_test_registry'] = module
    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', '_test_registry')

    from colony_manager.datatypes import reset_registry_cache
    reset_registry_cache()
    yield
    reset_registry_cache()
    sys.modules.pop('_test_registry', None)


def test_registered_key_resolves(fake_registry):
    from colony_manager.datatypes import load_description_class
    assert load_description_class('STUB') is _Stub


def test_unregistered_key_rejected(fake_registry):
    from colony_manager.datatypes import load_description_class
    with pytest.raises(ValueError):
        load_description_class('mmm_db.cftsdata.ABR')


def test_dotted_path_rejected_even_if_importable(fake_registry):
    """The original RCE: an importable module path used to be enough."""
    from colony_manager.datatypes import load_description_class
    with pytest.raises(ValueError):
        load_description_class('os.path')


def test_missing_env_var_raises_runtime_error(monkeypatch):
    monkeypatch.delenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', raising=False)
    from colony_manager.datatypes import (
        load_description_class, reset_registry_cache,
    )
    reset_registry_cache()
    with pytest.raises(RuntimeError):
        load_description_class('STUB')
    reset_registry_cache()


def test_non_subclass_value_rejected(monkeypatch):
    """The registry must refuse values that aren't DataTypeDescription."""
    import sys
    import types

    bad = types.ModuleType('_bad_registry')
    bad.DESCRIPTION_CLASSES = {'NOT_A_CLASS': 'just a string'}
    sys.modules['_bad_registry'] = bad
    monkeypatch.setenv('COLONY_MANAGER_DESCRIPTION_REGISTRY', '_bad_registry')

    from colony_manager.datatypes import (
        load_description_class, reset_registry_cache,
    )
    reset_registry_cache()
    try:
        with pytest.raises(RuntimeError):
            load_description_class('NOT_A_CLASS')
    finally:
        reset_registry_cache()
        sys.modules.pop('_bad_registry', None)
