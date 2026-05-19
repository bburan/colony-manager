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
    assert set(study.animals) == {a1, a2}


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
    assert animal not in study.animals


def test_add_study_animal_quick_add(logged_in_client, db_session):
    """The animal-detail "Enroll in study" button POSTs here.

    Exercises ``studies.add_study_animal`` end-to-end and verifies the
    animal lands in the study's animal collection.
    """
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='Q-1')
    study = _make_study(db_session, name='Quick-Add-Target')

    response = logged_in_client.post(
        f'/studies/add/{animal.id}',
        data={'study': str(study.id)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.expire_all()
    db_session.refresh(study)
    assert animal in study.animals


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


# ---------------------------------------------------------------------------
# Event matrix + shared-files (functions exposed for testability)
# ---------------------------------------------------------------------------

def _seed_study_with_events(db_session):
    """Two animals, two procedures, mix of completed/missing events."""
    from datetime import date
    from colony_manager.models import AnimalEvent, AnimalEventTag
    from .factories import (
        make_animal, make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='G-A')
    b = make_animal(db_session, species=species, custom_id='G-B')
    abr = make_procedure(db_session, name='ABR')
    cfts = make_procedure(db_session, name='CFTS')
    cochlea = make_procedure_target(db_session, name='Cochlea')
    cortex = make_procedure_target(db_session, name='Cortex')

    study = _make_study(db_session, name='Matrix-Study')
    study.animals.extend([a, b])

    on = date(2025, 12, 1)
    # A: complete ABR (both sides), CFTS-left only.
    db_session.add_all([
        AnimalEvent(animal_id=a.id, procedure_id=abr.id,
                    procedure_target_id=cochlea.id, side='Left',
                    scheduled_date=on, completion_date=on),
        AnimalEvent(animal_id=a.id, procedure_id=abr.id,
                    procedure_target_id=cochlea.id, side='Right',
                    scheduled_date=on, completion_date=on),
        AnimalEvent(animal_id=a.id, procedure_id=cfts.id,
                    procedure_target_id=cortex.id, side='Left',
                    scheduled_date=on, completion_date=on),
    ])
    # B: ABR-right only.
    db_session.add(AnimalEvent(
        animal_id=b.id, procedure_id=abr.id,
        procedure_target_id=cochlea.id, side='Right',
        scheduled_date=on, completion_date=on,
    ))
    db_session.commit()
    return study, a, b, abr, cfts, cochlea, cortex


def test_build_event_groups_empty_study(app, db_session):
    """A study with no animals yields an empty groups list."""
    from colony_manager_gui.routes.studies import _build_event_groups
    assert _build_event_groups([]) == []


def test_build_event_groups_basic_shape(app, db_session):
    """One group per (procedure, target). Columns are (side, tag)
    sub-buckets — since the seed has no tags, each side collapses to
    a single ``(untagged)`` column.
    """
    from colony_manager_gui.routes.studies import (
        _build_event_groups, _UNTAGGED,
    )
    study, a, b, abr, cfts, cochlea, cortex = _seed_study_with_events(db_session)
    animals = sorted(study.animals, key=lambda x: x.display_id)

    groups = _build_event_groups(animals)
    assert len(groups) == 2

    by_proc = {g['root_procedure'].name: g for g in groups}
    assert set(by_proc.keys()) == {'ABR', 'CFTS'}

    abr_group = by_proc['ABR']
    assert abr_group['target'].name == 'Cochlea'
    assert abr_group['total_events'] == 3  # 2 for G-A + 1 for G-B
    # No tags in the seed → one column per side, both labeled untagged.
    cols = abr_group['columns']
    assert [(c['side'], c['tag_label']) for c in cols] == [
        ('Left', '(untagged)'), ('Right', '(untagged)'),
    ]
    # Side colspan summary collapses repeats per side.
    assert abr_group['sides_summary'] == [
        {'side': 'Left', 'colspan': 1},
        {'side': 'Right', 'colspan': 1},
    ]
    # animals_missing counts rows with zero events in the group; both
    # animals have at least one ABR event, so 0.
    assert abr_group['animals_missing'] == 0

    rows_by_id = {r['animal'].custom_id: r for r in abr_group['rows']}
    left_key = ('Left', _UNTAGGED)
    right_key = ('Right', _UNTAGGED)
    # Each cell is now a list of sub-buckets (one per sub-procedure
    # under the root). With no sub-procedures here, each cell has a
    # single bucket with sub_label=''.
    assert len(rows_by_id['G-A']['cells'][left_key]) == 1
    assert rows_by_id['G-A']['cells'][left_key][0]['count'] == 1
    assert rows_by_id['G-A']['cells'][left_key][0]['sub_label'] == ''
    assert rows_by_id['G-A']['cells'][right_key][0]['count'] == 1
    assert rows_by_id['G-B']['cells'][left_key] is None
    assert rows_by_id['G-B']['cells'][right_key][0]['count'] == 1

    cfts_group = by_proc['CFTS']
    assert [c['side'] for c in cfts_group['columns']] == ['Left']
    assert cfts_group['animals_missing'] == 1  # G-B has no CFTS events
    cfts_rows = {r['animal'].custom_id: r for r in cfts_group['rows']}
    assert cfts_rows['G-A']['has_any'] is True
    assert cfts_rows['G-B']['has_any'] is False


def test_build_event_groups_splits_columns_by_tag(app, db_session):
    """An event with tag X and an event with tag Y on the same side
    produce two distinct sub-columns under that side.
    """
    from datetime import date
    from colony_manager_gui.routes.studies import _build_event_groups
    from colony_manager.models import AnimalEvent, AnimalEventTag
    from .factories import (
        make_animal, make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    procedure = make_procedure(db_session, name='ABR')
    target = make_procedure_target(db_session, name='Cochlea')

    baseline = AnimalEventTag(name='baseline')
    follow_up = AnimalEventTag(name='follow-up')
    db_session.add_all([baseline, follow_up])
    db_session.commit()

    study = _make_study(db_session, name='Tag-Split-Study')
    animal = make_animal(db_session, species=species, custom_id='T-1')
    study.animals.append(animal)

    # Two events on Left side, different tags. Plus one Left untagged.
    e1 = AnimalEvent(
        animal_id=animal.id, procedure_id=procedure.id,
        procedure_target_id=target.id, side='Left',
        scheduled_date=date(2025, 1, 5), completion_date=date(2025, 1, 5),
    )
    e1.tags = [baseline]
    e2 = AnimalEvent(
        animal_id=animal.id, procedure_id=procedure.id,
        procedure_target_id=target.id, side='Left',
        scheduled_date=date(2025, 2, 10), completion_date=date(2025, 2, 10),
    )
    e2.tags = [follow_up]
    e3 = AnimalEvent(  # untagged
        animal_id=animal.id, procedure_id=procedure.id,
        procedure_target_id=target.id, side='Left',
        scheduled_date=date(2025, 3, 1), completion_date=date(2025, 3, 1),
    )
    db_session.add_all([e1, e2, e3])
    db_session.commit()

    groups = _build_event_groups([animal])
    assert len(groups) == 1
    group = groups[0]
    # Three Left sub-columns: baseline, follow-up (alphabetical),
    # (untagged) last.
    labels = [c['tag_label'] for c in group['columns']]
    assert labels == ['baseline', 'follow-up', '(untagged)']
    # All three under the same Left side.
    assert group['sides_summary'] == [{'side': 'Left', 'colspan': 3}]


def test_build_event_groups_cell_shows_date_range(app, db_session):
    """When multiple events fall into the same (side, tag) bucket,
    the cell carries min_date, max_date, and count.
    """
    from datetime import date
    from colony_manager_gui.routes.studies import (
        _build_event_groups, _UNTAGGED,
    )
    from colony_manager.models import AnimalEvent, AnimalEventTag
    from .factories import (
        make_animal, make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    animal = make_animal(db_session, species=species, custom_id='R-1')
    baseline = AnimalEventTag(name='baseline')
    db_session.add(baseline)
    db_session.commit()

    for d in (date(2025, 1, 10), date(2025, 1, 15), date(2025, 2, 1)):
        event = AnimalEvent(
            animal_id=animal.id, procedure_id=procedure.id,
            procedure_target_id=target.id, side='Left',
            scheduled_date=d, completion_date=d,
        )
        event.tags = [baseline]
        db_session.add(event)
    db_session.commit()

    groups = _build_event_groups([animal])
    cell = groups[0]['rows'][0]['cells'][('Left', baseline.id)]
    # Single sub-bucket since all events share the same root procedure
    # with no sub-procedures.
    assert len(cell) == 1
    assert cell[0]['count'] == 3
    assert cell[0]['min_date'] == date(2025, 1, 10)
    assert cell[0]['max_date'] == date(2025, 2, 1)


def test_build_event_groups_multi_tagged_event_in_both_buckets(app, db_session):
    """An event with two tags lands in two cells — one per tag.
    Counts therefore reflect "events carrying this tag", not the raw
    event-row count.
    """
    from datetime import date
    from colony_manager_gui.routes.studies import _build_event_groups
    from colony_manager.models import AnimalEvent, AnimalEventTag
    from .factories import (
        make_animal, make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    animal = make_animal(db_session, species=species, custom_id='M-1')
    a_tag = AnimalEventTag(name='alpha')
    b_tag = AnimalEventTag(name='beta')
    db_session.add_all([a_tag, b_tag])
    db_session.commit()

    event = AnimalEvent(
        animal_id=animal.id, procedure_id=procedure.id,
        procedure_target_id=target.id, side='Left',
        scheduled_date=date(2025, 1, 5),
        completion_date=date(2025, 1, 5),
    )
    event.tags = [a_tag, b_tag]
    db_session.add(event)
    db_session.commit()

    groups = _build_event_groups([animal])
    cells = groups[0]['rows'][0]['cells']
    # Same event contributes one count to each tag bucket.
    assert cells[('Left', a_tag.id)][0]['count'] == 1
    assert cells[('Left', b_tag.id)][0]['count'] == 1
    # And the group's overall event count is still 1.
    assert groups[0]['total_events'] == 1


def test_build_event_groups_collapses_sub_procedures_under_root(app, db_session):
    """Events under different sub-procedures of the same root collapse
    into a single (root_procedure, target) panel, with the sub-procedure
    name surfaced as the cell's ``sub_label``.
    """
    from datetime import date
    from colony_manager_gui.routes.studies import (
        _build_event_groups, _UNTAGGED,
    )
    from colony_manager.models import AnimalEvent
    from .factories import (
        make_animal, make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    noise = make_procedure(db_session, name='Noise exposure')
    db_100 = make_procedure(db_session, name='100 dB SPL', parent=noise)
    db_103 = make_procedure(db_session, name='103 dB SPL', parent=noise)
    target = make_procedure_target(db_session, name='Cochlea')

    animal = make_animal(db_session, species=species, custom_id='N-1')

    db_session.add_all([
        AnimalEvent(
            animal_id=animal.id, procedure_id=db_100.id,
            procedure_target_id=target.id, side='Left',
            scheduled_date=date(2025, 1, 5),
            completion_date=date(2025, 1, 5),
        ),
        AnimalEvent(
            animal_id=animal.id, procedure_id=db_103.id,
            procedure_target_id=target.id, side='Left',
            scheduled_date=date(2025, 2, 10),
            completion_date=date(2025, 2, 10),
        ),
    ])
    db_session.commit()

    groups = _build_event_groups([animal])
    # Single panel keyed on the root procedure.
    assert len(groups) == 1
    g = groups[0]
    assert g['root_procedure'].name == 'Noise exposure'
    assert g['total_events'] == 2

    cell = g['rows'][0]['cells'][('Left', _UNTAGGED)]
    # Two sub-buckets, sorted alphabetically (both labeled).
    sub_labels = [b['sub_label'] for b in cell]
    assert sub_labels == ['100 dB SPL', '103 dB SPL']
    assert cell[0]['min_date'] == date(2025, 1, 5)
    assert cell[1]['min_date'] == date(2025, 2, 10)


def test_find_shared_data_files_returns_multi_animal_links(app, db_session):
    """A Data file whose events span 2+ animals in the study is listed."""
    from datetime import date
    from colony_manager_gui.routes.studies import _find_shared_data_files
    from colony_manager.models import AnimalEvent, AnimalEventData
    from .factories import (
        make_animal, make_animal_event_data_type, make_data_location,
        make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='SH-A')
    b = make_animal(db_session, species=species, custom_id='SH-B')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)

    on = date(2025, 6, 1)
    event_a = AnimalEvent(
        animal_id=a.id, procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=on, completion_date=on,
    )
    event_b = AnimalEvent(
        animal_id=b.id, procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=on, completion_date=on,
    )
    db_session.add_all([event_a, event_b])
    db_session.commit()

    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    location = make_data_location(db_session, datatype=dtype, base_path='/tmp')
    shared = AnimalEventData(
        datatype_id=dtype.id, location_id=location.id,
        relative_path='shared.txt', name='shared.txt', status='unreviewed',
    )
    shared.events = [event_a, event_b]
    db_session.add(shared)
    db_session.commit()

    result = _find_shared_data_files([a, b])
    assert len(result) == 1
    file_obj, animals = result[0]
    assert file_obj.id == shared.id
    assert {an.id for an in animals} == {a.id, b.id}


def test_find_shared_data_files_ignores_single_animal_links(app, db_session):
    """A file linked to only one animal isn't shared — excluded."""
    from datetime import date
    from colony_manager_gui.routes.studies import _find_shared_data_files
    from colony_manager.models import AnimalEvent, AnimalEventData
    from .factories import (
        make_animal, make_animal_event_data_type, make_data_location,
        make_procedure, make_procedure_target, make_species,
    )

    species = make_species(db_session)
    a = make_animal(db_session, species=species, custom_id='ONE-A')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    event = AnimalEvent(
        animal_id=a.id, procedure_id=procedure.id,
        procedure_target_id=target.id,
        scheduled_date=date(2025, 6, 1),
        completion_date=date(2025, 6, 1),
    )
    db_session.add(event)
    db_session.commit()

    dtype = make_animal_event_data_type(
        db_session, default_procedure=procedure,
    )
    location = make_data_location(db_session, datatype=dtype, base_path='/tmp')
    f = AnimalEventData(
        datatype_id=dtype.id, location_id=location.id,
        relative_path='solo.txt', name='solo.txt', status='unreviewed',
    )
    f.events = [event]
    db_session.add(f)
    db_session.commit()

    assert _find_shared_data_files([a]) == []


def test_view_study_renders_event_groups(logged_in_client, db_session):
    """End-to-end: GET /studies/<id> renders the per-procedure
    accordion card with the seeded animals and procedures visible.
    """
    study, _a, _b, _abr, _cfts, _cochlea, _cortex = _seed_study_with_events(db_session)
    response = logged_in_client.get(f'/studies/{study.id}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Event Coverage by Procedure' in body
    # Both procedure groups present in the accordion headers.
    assert 'ABR' in body
    assert 'CFTS' in body
    # Animals show up inside the panel body.
    assert 'G-A' in body
    assert 'G-B' in body
    # The CFTS group has 1 missing animal (G-B); incomplete badge
    # should appear at least once on the page.
    assert 'incomplete' in body
