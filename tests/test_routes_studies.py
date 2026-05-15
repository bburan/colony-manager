"""Smoke + targeted coverage for the ``studies`` blueprint.

Thirteen Model.query sites converted across list/view/create/update/
add/remove/bulk_assign/modals. The two ``form.animals.query = ...``
assignments inside view_study and add_study_animals use the legacy
``db.session.query(...)`` API (WTForms-SQLAlchemy's QuerySelectField
expects a Query object, not a Select).

Test scope: list with seeded studies, view with seeded study,
404 paths, create + update POSTs, add/remove animals, modal renders.
"""
from sqlalchemy import select

from colony_manager.models import Study

from .factories import make_animal, make_species


def _make_study(session, name='Study-1', description='desc'):
    study = Study(name=name, description=description)
    session.add(study)
    session.commit()
    return study


# ---------------------------------------------------------------------------
# List + detail
# ---------------------------------------------------------------------------

def test_list_studies_returns_200(logged_in_client, db_session):
    _make_study(db_session, name='Behavior Study')
    response = logged_in_client.get('/studies/')
    assert response.status_code == 200
    assert b'Behavior Study' in response.data


def test_view_study_returns_200(logged_in_client, db_session):
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='S-1')
    study = _make_study(db_session, name='View-Study')
    response = logged_in_client.get(f'/studies/{study.id}')
    assert response.status_code == 200
    assert b'View-Study' in response.data


def test_view_study_returns_404_for_unknown_id(logged_in_client):
    response = logged_in_client.get('/studies/99999')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Create + update
# ---------------------------------------------------------------------------

def test_create_study_persists(logged_in_client, db_session):
    response = logged_in_client.post(
        '/studies/create',
        data={'name': 'New Study', 'description': 'Just made'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    persisted = db_session.scalars(
        select(Study).where(Study.name == 'New Study')
    ).one()
    assert persisted.description == 'Just made'


def test_update_study_persists(logged_in_client, db_session):
    study = _make_study(db_session, name='Original')
    response = logged_in_client.post(
        f'/studies/{study.id}/update',
        data={'name': 'Renamed', 'description': 'Updated desc'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(study)
    assert study.name == 'Renamed'
    assert study.description == 'Updated desc'


# ---------------------------------------------------------------------------
# Animal membership
# ---------------------------------------------------------------------------

def test_bulk_assign_animals_to_study(logged_in_client, db_session):
    species = make_species(db_session)
    a1 = make_animal(db_session, species=species, custom_id='BA-1')
    a2 = make_animal(db_session, species=species, custom_id='BA-2')
    study = _make_study(db_session, name='Bulk')

    response = logged_in_client.post(
        '/studies/bulk_assign',
        data={'study_id': str(study.id),
              'animal_ids': [str(a1.id), str(a2.id)]},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(study)
    assert set(study.animals.all()) == {a1, a2}


def test_bulk_assign_with_missing_inputs_redirects(logged_in_client):
    response = logged_in_client.post(
        '/studies/bulk_assign', data={}, follow_redirects=False,
    )
    # No 500; just a flashed warning + redirect.
    assert response.status_code == 302


def test_remove_study_animal(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='R-1')
    study = _make_study(db_session, name='Remove-Study')
    study.animals.append(animal)
    db_session.commit()

    response = logged_in_client.post(
        f'/studies/{study.id}/animals/{animal.id}/delete',
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(study)
    assert animal not in study.animals.all()


def test_remove_study_animal_404_for_unknown_study(logged_in_client, db_session):
    animal = make_animal(db_session)
    response = logged_in_client.post(
        f'/studies/99999/animals/{animal.id}/delete',
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

def test_create_study_modal_renders(logged_in_client):
    response = logged_in_client.get('/studies/create_modal')
    assert response.status_code == 200


def test_edit_study_modal_renders(logged_in_client, db_session):
    study = _make_study(db_session, name='Edit-Modal-Study')
    response = logged_in_client.get(f'/studies/{study.id}/edit_modal')
    assert response.status_code == 200


def test_edit_study_modal_returns_404_for_unknown(logged_in_client):
    response = logged_in_client.get('/studies/99999/edit_modal')
    assert response.status_code == 404
