"""Smoke + filter coverage for the ``cages`` blueprint.

Seven Model.query sites converted:
* ``_attach_cage_animals`` bulk Animal load.
* ``list_cages`` Cage base query.
* ``Source.query.order_by(...).all()`` for the filter dropdown.
* Four ``Cage.query.get_or_404(...)`` lookups (view, update, update_note,
  edit_note_modal).

Plus two ``db.session.query(...)`` subqueries converted to ``select(...).subquery()``.

Filter tests exercise the ``Cage.animals.any(...)``, occupancy
subquery join, and sort paths to catch SQL-compilation regressions
in the refactor.
"""
from datetime import date, timedelta

from sqlalchemy import select

from colony_manager.models import Animal, Cage

from .factories import make_animal, make_cage, make_source, make_species


# ---------------------------------------------------------------------------
# Filter / sort smoke
# ---------------------------------------------------------------------------

def test_list_cages_with_seeded_data(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='G001')
    make_animal(db_session, cage=cage, species=species)
    response = logged_in_client.get('/cages/')
    assert response.status_code == 200
    assert b'G001' in response.data


def test_list_cages_status_inactive_filter(logged_in_client, db_session):
    species = make_species(db_session)
    empty_cage = make_cage(db_session, species=species, custom_id='EMPTY')
    response = logged_in_client.get('/cages/?status_filter=inactive')
    assert response.status_code == 200
    assert b'EMPTY' in response.data


def test_list_cages_sex_filter_male(logged_in_client, db_session):
    species = make_species(db_session)
    male_only = make_cage(db_session, species=species, custom_id='M-CAGE')
    make_animal(db_session, cage=male_only, species=species, sex='male')
    mixed = make_cage(db_session, species=species, custom_id='X-CAGE')
    make_animal(db_session, cage=mixed, species=species, sex='male')
    make_animal(db_session, cage=mixed, species=species, sex='female')

    response = logged_in_client.get('/cages/?sex_filter=male')
    assert response.status_code == 200
    assert b'M-CAGE' in response.data
    assert b'X-CAGE' not in response.data


def test_list_cages_occupancy_empty_filter(logged_in_client, db_session):
    """Exercises the active_count subquery + filter path."""
    species = make_species(db_session)
    make_cage(db_session, species=species, custom_id='EMPTY-1')
    response = logged_in_client.get('/cages/?occupancy_filter=empty&status_filter=all')
    assert response.status_code == 200
    assert b'EMPTY-1' in response.data


def test_list_cages_sort_by_age(logged_in_client, db_session):
    """Exercises the total_count_subq join + max_dob sort path."""
    species = make_species(db_session)
    older = make_cage(db_session, species=species, custom_id='OLD')
    make_animal(
        db_session, cage=older, species=species,
        dob=date.today() - timedelta(days=200),
    )
    younger = make_cage(db_session, species=species, custom_id='YOUNG')
    make_animal(
        db_session, cage=younger, species=species,
        dob=date.today() - timedelta(days=10),
    )

    response = logged_in_client.get('/cages/?sort_by=age&sort_dir=asc')
    assert response.status_code == 200


def test_list_cages_source_filter(logged_in_client, db_session):
    species = make_species(db_session)
    source = make_source(db_session, name='SourceA')
    matched = make_cage(db_session, species=species, custom_id='SRC-MATCH')
    make_animal(
        db_session, cage=matched, species=species, source=source,
    )
    unmatched = make_cage(db_session, species=species, custom_id='SRC-MISS')
    make_animal(db_session, cage=unmatched, species=species)

    response = logged_in_client.get(
        f'/cages/?source_id={source.id}&status_filter=all'
    )
    assert response.status_code == 200
    assert b'SRC-MATCH' in response.data
    assert b'SRC-MISS' not in response.data


# ---------------------------------------------------------------------------
# Detail view (get_or_404 conversion)
# ---------------------------------------------------------------------------

def test_view_cage_returns_200_for_real_cage(logged_in_client, db_session):
    cage = make_cage(db_session, custom_id='VIEW-1')
    response = logged_in_client.get(f'/cages/{cage.id}')
    assert response.status_code == 200
    assert b'VIEW-1' in response.data


def test_view_cage_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/cages/99999')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

def test_create_cage_modal_renders(logged_in_client):
    response = logged_in_client.get('/cages/create_modal')
    assert response.status_code == 200


def test_edit_note_modal_renders(logged_in_client, db_session):
    cage = make_cage(db_session, custom_id='NOTE-1')
    response = logged_in_client.get(f'/cages/{cage.id}/edit_note_modal')
    assert response.status_code == 200


def test_edit_note_modal_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/cages/99999/edit_note_modal')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Create (exercises the form path)
# ---------------------------------------------------------------------------

def test_create_cage_persists_cage_and_animals(logged_in_client, db_session):
    species = make_species(db_session)
    source = make_source(db_session)

    response = logged_in_client.post('/cages/create', data={
        'custom_id': 'NEW-1',
        'species': str(species.id),
        'source': str(source.id),
        'sex': 'male',
        'number_of_animals': '3',
        'dob': date.today().isoformat(),
        'notes': '',
    }, follow_redirects=False)
    assert response.status_code == 302

    cage = db_session.scalars(
        select(Cage).where(Cage.custom_id == 'NEW-1')
    ).one()
    animals = db_session.scalars(
        select(Animal).where(Animal.cage_id == cage.id)
    ).all()
    assert len(animals) == 3
    assert all(a.sex == 'male' for a in animals)


def test_update_cage_note(logged_in_client, db_session):
    cage = make_cage(db_session, custom_id='NOTE-2', notes='old')
    response = logged_in_client.post(
        f'/cages/{cage.id}/update_note',
        data={'notes': 'new note'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(cage)
    assert cage.notes == 'new note'
