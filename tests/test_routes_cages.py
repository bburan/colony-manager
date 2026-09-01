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


def test_list_cages_has_edit_button(logged_in_client, db_session):
    """Each row exposes an edit button targeting the cage-details modal."""
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='G002')
    make_animal(db_session, cage=cage, species=species)  # so it's active/shown
    response = logged_in_client.get('/cages/')
    assert response.status_code == 200
    assert f'/cages/{cage.id}/edit_details_modal'.encode() in response.data


def test_list_cages_target_age_column(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='TARGET')
    dob = date.today()
    make_animal(db_session, cage=cage, species=species, dob=dob)
    expected = (dob + timedelta(days=56)).strftime('%Y-%m-%d').encode()
    response = logged_in_client.get('/cages/?target_age=8w&status_filter=all')
    assert response.status_code == 200
    assert b'Date of target age' in response.data
    assert expected in response.data


def test_list_cages_target_age_range(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='RANGE')
    dob_young = date.today()
    dob_old = date.today() - timedelta(days=10)
    make_animal(db_session, cage=cage, species=species, dob=dob_young)
    make_animal(db_session, cage=cage, species=species, dob=dob_old)
    earliest = (dob_old + timedelta(days=56)).strftime('%Y-%m-%d')
    latest = (dob_young + timedelta(days=56)).strftime('%Y-%m-%d')
    response = logged_in_client.get('/cages/?target_age=8+weeks&status_filter=all')
    assert response.status_code == 200
    assert f'{earliest} to {latest}'.encode() in response.data


def test_list_cages_target_age_excludes_terminated(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='TERM')
    dob = date.today()
    make_animal(db_session, cage=cage, species=species, dob=dob)
    dead = make_animal(db_session, cage=cage, species=species,
                       dob=date.today() - timedelta(days=10))
    dead.terminate(termination_date=date.today())
    db_session.commit()
    expected = (dob + timedelta(days=56)).strftime('%Y-%m-%d').encode()
    dead_date = (date.today() - timedelta(days=10) + timedelta(days=56)).strftime('%Y-%m-%d').encode()
    response = logged_in_client.get('/cages/?target_age=8w&status_filter=all')
    assert response.status_code == 200
    # Only the living animal contributes -> single date, not a range.
    assert expected in response.data
    assert dead_date not in response.data


def test_list_cages_target_age_missing_unit_errors(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='NOUNIT')
    make_animal(db_session, cage=cage, species=species, dob=date.today())
    response = logged_in_client.get('/cages/?target_age=8&status_filter=all')
    assert response.status_code == 200
    assert b'Include a unit' in response.data
    # No column rendered on an invalid target age.
    assert b'Date of target age' not in response.data


def test_list_cages_blank_target_age_hides_column(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='NOCOL')
    make_animal(db_session, cage=cage, species=species, dob=date.today())
    response = logged_in_client.get('/cages/?status_filter=all')
    assert response.status_code == 200
    assert b'Date of target age' not in response.data


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


def test_view_cage_renders_with_unassigned_custom_id(logged_in_client, db_session):
    """Regression: cages whose animals include any ``custom_id=None`` row
    used to crash with ``TypeError: '<' not supported between instances
    of 'str' and 'NoneType'`` because the template sorted via Jinja's
    ``|sort(attribute=...)`` without None-handling.
    """
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='MIX-1')
    # One animal with a custom_id, one without.
    make_animal(db_session, cage=cage, species=species, custom_id='M-A')
    no_id = make_animal(db_session, cage=cage, species=species)
    no_id.custom_id = None
    db_session.commit()

    response = logged_in_client.get(f'/cages/{cage.id}')
    assert response.status_code == 200
    assert b'M-A' in response.data


def test_view_cage_renders_with_all_animals_unassigned(logged_in_client, db_session):
    """Same regression, but every animal in the cage has custom_id=None."""
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='UNS-1')
    for _ in range(2):
        a = make_animal(db_session, cage=cage, species=species)
        a.custom_id = None
    db_session.commit()

    response = logged_in_client.get(f'/cages/{cage.id}')
    assert response.status_code == 200


def test_view_cage_shows_delete_button_for_deletable_animal(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='DELBTN')
    animal = make_animal(db_session, cage=cage, species=species)
    animal.custom_id = None  # no ID, no events -> deletable
    db_session.commit()

    response = logged_in_client.get(f'/cages/{cage.id}')
    assert response.status_code == 200
    assert f'/animals/{animal.id}/delete'.encode() in response.data


def test_view_cage_hides_delete_button_for_animal_with_id(logged_in_client, db_session):
    species = make_species(db_session)
    cage = make_cage(db_session, species=species, custom_id='NODEL')
    animal = make_animal(db_session, cage=cage, species=species, custom_id='KEEP-1')

    response = logged_in_client.get(f'/cages/{cage.id}')
    assert response.status_code == 200
    assert f'/animals/{animal.id}/delete'.encode() not in response.data


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


def test_edit_cage_details_modal_renders(logged_in_client, db_session):
    cage = make_cage(db_session, custom_id='ID-1', notes='keep cool')
    response = logged_in_client.get(f'/cages/{cage.id}/edit_details_modal')
    assert response.status_code == 200
    assert b'ID-1' in response.data
    # The details modal now includes the notes field, pre-filled.
    assert b'Notes' in response.data
    assert b'keep cool' in response.data


def test_edit_cage_details_modal_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/cages/99999/edit_details_modal')
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


def test_update_cage_details_persists_id_and_species(logged_in_client, db_session):
    cage = make_cage(db_session, custom_id='ID-2')
    new_species = make_species(db_session)
    response = logged_in_client.post(
        f'/cages/{cage.id}/update_details',
        data={'custom_id': 'ID-2-FIXED', 'species': str(new_species.id)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(cage)
    assert cage.custom_id == 'ID-2-FIXED'
    assert cage.species_id == new_species.id


def test_update_cage_details_persists_notes(logged_in_client, db_session):
    cage = make_cage(db_session, custom_id='ID-N')
    response = logged_in_client.post(
        f'/cages/{cage.id}/update_details',
        data={
            'custom_id': 'ID-N', 'species': str(cage.species_id),
            'notes': 'handle with care',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(cage)
    assert cage.notes == 'handle with care'


def test_update_cage_details_allows_resubmitting_same_id(logged_in_client, db_session):
    """Submitting the modal without changing the ID shouldn't trip the
    uniqueness check against the cage's own current row."""
    cage = make_cage(db_session, custom_id='ID-3')
    response = logged_in_client.post(
        f'/cages/{cage.id}/update_details',
        data={'custom_id': 'ID-3', 'species': str(cage.species_id)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(cage)
    assert cage.custom_id == 'ID-3'


def test_update_cage_details_rejects_duplicate_id(logged_in_client, db_session):
    make_cage(db_session, custom_id='ID-4')
    other = make_cage(db_session, custom_id='ID-5')
    response = logged_in_client.post(
        f'/cages/{other.id}/update_details',
        data={'custom_id': 'ID-4', 'species': str(other.species_id)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(other)
    assert other.custom_id == 'ID-5'


# ---------------------------------------------------------------------------
# Single housing
# ---------------------------------------------------------------------------

def test_single_housing_modal_renders_with_animal_display_id(logged_in_client, db_session):
    """Modal pre-populates the cage ID field with the animal's display_id."""
    animal = make_animal(db_session, custom_id='SH-A1')
    response = logged_in_client.get(f'/animals/{animal.id}/single_housing_modal')
    assert response.status_code == 200
    assert b'SH-A1' in response.data


def test_single_housing_creates_cage_and_moves_animal(logged_in_client, db_session):
    """Happy path: new cage is created, animal is reassigned, redirect to new cage."""
    animal = make_animal(db_session, custom_id='SH-B1')
    original_cage_id = animal.cage_id

    response = logged_in_client.post(
        f'/animals/{animal.id}/single_housing',
        data={'cage_id': 'SH-B1'},
        follow_redirects=False,
    )
    assert response.status_code == 302

    db_session.refresh(animal)
    new_cage = db_session.get(Cage, animal.cage_id)
    assert new_cage is not None
    assert new_cage.custom_id == 'SH-B1'
    assert new_cage.species_id == animal.species_id
    assert animal.cage_id != original_cage_id
    assert response.location.endswith(f'/cages/{new_cage.id}')


def test_single_housing_rejects_duplicate_cage_id(logged_in_client, db_session):
    """If the requested cage ID already exists the form is rejected."""
    existing = make_cage(db_session, custom_id='SH-DUP')
    animal = make_animal(db_session, custom_id='SH-C1')

    response = logged_in_client.post(
        f'/animals/{animal.id}/single_housing',
        data={'cage_id': 'SH-DUP'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(animal)
    assert animal.cage_id != existing.id
