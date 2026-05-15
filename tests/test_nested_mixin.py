"""Tests for ``NestedMixin.get_ordered`` / ``descendant_ids``.

The mixin powers tag and procedure tree traversal across the app —
the filter UIs on Cages, Animals, and Histology list views, and the
nested-form parent picker. After the refactor both methods take an
explicit ``session``; tests pass the per-test ``db_session`` directly.

``AnimalTag`` exercises the mixin here. The other consumers
(``AnimalProcedure``, ``AnimalEventTag``, ``EarTag``) share the same
mixin code path, so coverage carries over.
"""
from colony_manager.models import AnimalTag


def _make_tag(session, name, parent=None):
    tag = AnimalTag(name=name, parent_id=parent.id if parent else None)
    session.add(tag)
    session.commit()
    return tag


# ---------------------------------------------------------------------------
# display_name
# ---------------------------------------------------------------------------

def test_display_name_root(db_session):
    root = _make_tag(db_session, 'Root')
    assert root.display_name == 'Root'


def test_display_name_nested_uses_parent_chain(db_session):
    root = _make_tag(db_session, 'Root')
    child = _make_tag(db_session, 'Child', parent=root)
    grand = _make_tag(db_session, 'Grand', parent=child)
    assert grand.display_name == 'Root > Child > Grand'


# ---------------------------------------------------------------------------
# get_ordered
# ---------------------------------------------------------------------------

def test_get_ordered_empty_table(db_session):
    assert AnimalTag.get_ordered(db_session) == []


def test_get_ordered_returns_depth_first_with_alphabetised_siblings(db_session):
    """Order contract: roots sorted by name; each parent's children
    immediately follow it in alphabetical (case-insensitive) order.
    """
    # Insert deliberately out of order so the test fails if the method
    # returns rows in insertion / id order.
    bravo = _make_tag(db_session, 'bravo')          # root
    alpha = _make_tag(db_session, 'Alpha')          # root (capitalized to verify case-insensitive sort)
    b1 = _make_tag(db_session, 'b1', parent=bravo)
    a2 = _make_tag(db_session, 'a2', parent=alpha)
    a1 = _make_tag(db_session, 'a1', parent=alpha)
    a1a = _make_tag(db_session, 'a1a', parent=a1)

    ordered = AnimalTag.get_ordered(db_session)
    assert [t.name for t in ordered] == [
        'Alpha',     # root: alpha sorts before bravo
        'a1',        # alpha's children: a1 before a2
        'a1a',       # a1's only child, depth-first
        'a2',
        'bravo',
        'b1',
    ]


def test_get_ordered_case_insensitive_sibling_sort(db_session):
    _make_tag(db_session, 'zebra')
    _make_tag(db_session, 'Apple')
    _make_tag(db_session, 'banana')
    ordered = AnimalTag.get_ordered(db_session)
    assert [t.name for t in ordered] == ['Apple', 'banana', 'zebra']


# ---------------------------------------------------------------------------
# descendant_ids
# ---------------------------------------------------------------------------

def test_descendant_ids_includes_root(db_session):
    root = _make_tag(db_session, 'Lonely')
    assert AnimalTag.descendant_ids(db_session, root.id) == {root.id}


def test_descendant_ids_full_subtree(db_session):
    """Returns the root + every descendant transitively."""
    root = _make_tag(db_session, 'Root')
    c1 = _make_tag(db_session, 'C1', parent=root)
    c2 = _make_tag(db_session, 'C2', parent=root)
    g1 = _make_tag(db_session, 'G1', parent=c1)
    g2 = _make_tag(db_session, 'G2', parent=c1)
    gg1 = _make_tag(db_session, 'GG1', parent=g1)
    # A sibling subtree that must NOT appear.
    other_root = _make_tag(db_session, 'Other')
    _make_tag(db_session, 'OtherChild', parent=other_root)

    expected = {root.id, c1.id, c2.id, g1.id, g2.id, gg1.id}
    assert AnimalTag.descendant_ids(db_session, root.id) == expected


def test_descendant_ids_returns_only_root_when_no_children(db_session):
    a = _make_tag(db_session, 'A')
    b = _make_tag(db_session, 'B', parent=a)  # child of A, not B
    assert AnimalTag.descendant_ids(db_session, b.id) == {b.id}


def test_descendant_ids_handles_unknown_id_gracefully(db_session):
    """An id with no row in the table should yield just itself.

    Real-world: filter forms POST stale ids when a tag is deleted
    between page load and submit. The method must not raise.
    """
    _make_tag(db_session, 'A')
    assert AnimalTag.descendant_ids(db_session, 99999) == {99999}
