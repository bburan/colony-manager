"""Tests for the dosage-protocol settings CRUD and the animal-page
dosage calculator / log-dose flow.

The settings routes mirror the DataType+DataLocation pattern: a single
``DosageProtocolForm`` with parallel ``drug_name`` / ``drug_dose`` /
``drug_concentration`` / ``drug_id`` arrays parsed straight out of
``request.form``. Tests cover create with drugs, edit (add + remove),
and delete-cascade.

The animal-page flow has three endpoints — modal render, live HTMX
calculate, and POST log-dose (which writes an AnimalEvent with both
``completion_date`` and ``completion_time`` populated).
"""
from datetime import date, datetime, time

from sqlalchemy import select

from colony_manager.models import (
    AnimalEvent, DosageProtocol, DosageProtocolDrug,
)
from colony_manager_gui.routes.animals import _compute_dosage, _format_dose_notes

from .factories import (
    make_animal, make_dosage_protocol, make_event, make_procedure,
    make_procedure_target, make_species,
)


# ---------------------------------------------------------------------------
# Volume math (no DB)
# ---------------------------------------------------------------------------

class _StubDrug:
    def __init__(self, dose, conc, name='stub'):
        self.dose_mg_per_kg = dose
        self.concentration_mg_per_ml = conc
        self.name = name


class _StubProtocol:
    def __init__(self, drugs):
        self.drugs = drugs


def test_compute_dosage_volume_for_known_weight():
    # 100 mg/kg @ 100 mg/mL on a 25 g mouse = 0.025 mL
    protocol = _StubProtocol([_StubDrug(100.0, 100.0)])
    rows, total = _compute_dosage(protocol, weight_g=25.0)
    assert len(rows) == 1
    assert rows[0]['dose_mg'] == 2.5
    assert rows[0]['volume_ml'] == 0.025
    assert total == 0.025


def test_format_dose_notes_has_line_per_drug_with_concentration():
    """The notes string is what ends up on the AnimalEvent forever,
    so it must capture concentration alongside dose+volume (protocols
    can be edited later) and put each drug on its own line so the
    template can render it readably."""
    class _StubProto:
        name = 'CFTS (ket/xyl)'
    drugs = [_StubDrug(100.0, 100.0, name='Ketamine'),
             _StubDrug(10.0, 20.0, name='Xylazine')]
    protocol = _StubProto()
    protocol_drugs = _StubProtocol(drugs)
    rows, _ = _compute_dosage(protocol_drugs, weight_g=25.0)
    notes = _format_dose_notes(protocol, weight_g=25.0, rows=rows)

    lines = notes.split('\n')
    # Header + one line per drug.
    assert len(lines) == 3
    assert 'CFTS (ket/xyl)' in lines[0]
    assert '25.00 g' in lines[0]

    ket_line = next(l for l in lines if 'Ketamine' in l)
    xyl_line = next(l for l in lines if 'Xylazine' in l)
    # Dose, concentration, and volume each appear on the drug's line.
    assert '100' in ket_line and 'mg/kg' in ket_line
    assert '100' in ket_line and 'mg/mL' in ket_line
    assert '0.025 mL' in ket_line
    assert '10' in xyl_line and '20' in xyl_line
    assert 'mL' in xyl_line


def test_compute_dosage_zero_concentration_is_safe():
    protocol = _StubProtocol([_StubDrug(10.0, 0.0), _StubDrug(5.0, 5.0)])
    rows, total = _compute_dosage(protocol, weight_g=20.0)
    assert rows[0]['volume_ml'] is None  # guarded against /0
    assert rows[1]['volume_ml'] == (5.0 * 0.020) / 5.0
    # Total excludes the zero-concentration row.
    assert total == rows[1]['volume_ml']


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------

def test_create_dosage_protocol_with_drugs(logged_in_client, db_session):
    procedure = make_procedure(db_session, name='CFTS-create')
    target = make_procedure_target(db_session, name='Target-create')

    response = logged_in_client.post(
        '/settings/dosage_protocol/create',
        data={
            'name': 'Mouse: CFTS (ket/xyl)',
            'procedure': str(procedure.id),
            'procedure_target': str(target.id),
            'notes': 'standard cocktail',
            # Two drug rows submitted as parallel arrays.
            'drug_id': ['', ''],
            'drug_name': ['Ketamine', 'Xylazine'],
            'drug_dose': ['100', '10'],
            'drug_concentration': ['100', '20'],
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    db_session.expire_all()
    protocol = db_session.scalars(
        select(DosageProtocol).where(
            DosageProtocol.name == 'Mouse: CFTS (ket/xyl)'
        )
    ).one()
    drugs = sorted(protocol.drugs, key=lambda d: d.position)
    assert [d.name for d in drugs] == ['Ketamine', 'Xylazine']
    assert [d.dose_mg_per_kg for d in drugs] == [100.0, 10.0]
    assert [d.concentration_mg_per_ml for d in drugs] == [100.0, 20.0]


def test_create_dosage_protocol_rejects_duplicate(logged_in_client, db_session):
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    make_dosage_protocol(
        db_session, name='Dup-Protocol',
        procedure=procedure, procedure_target=target,
    )

    response = logged_in_client.post(
        '/settings/dosage_protocol/create',
        data={
            'name': 'Dup-Protocol',
            'procedure': str(procedure.id),
            'procedure_target': str(target.id),
            'drug_id': [''], 'drug_name': ['A'],
            'drug_dose': ['1'], 'drug_concentration': ['1'],
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 400)
    # Only the one we seeded should exist.
    protocols = db_session.scalars(
        select(DosageProtocol).where(DosageProtocol.name == 'Dup-Protocol')
    ).all()
    assert len(protocols) == 1


def test_update_dosage_protocol_adds_and_removes_drug(logged_in_client, db_session):
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    protocol = make_dosage_protocol(
        db_session, name='To-Edit', procedure=procedure,
        procedure_target=target,
        drugs=[('Ketamine', 100.0, 100.0), ('Xylazine', 10.0, 20.0)],
    )
    keep_id = next(d.id for d in protocol.drugs if d.name == 'Ketamine')

    # Keep ketamine (with its existing id), drop xylazine, and add a new
    # acepromazine row (blank id => new). Updated dose tests the in-place
    # patch path so versioned history stays coherent.
    response = logged_in_client.post(
        f'/settings/dosage_protocol/{protocol.id}/update',
        data={
            'name': 'To-Edit',
            'procedure': str(procedure.id),
            'procedure_target': str(target.id),
            'drug_id': [str(keep_id), ''],
            'drug_name': ['Ketamine', 'Acepromazine'],
            'drug_dose': ['80', '1'],
            'drug_concentration': ['100', '10'],
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    db_session.expire_all()
    refreshed = db_session.get(DosageProtocol, protocol.id)
    names = sorted(d.name for d in refreshed.drugs)
    assert names == ['Acepromazine', 'Ketamine']
    ketamine = next(d for d in refreshed.drugs if d.name == 'Ketamine')
    assert ketamine.id == keep_id  # in-place update, not delete+insert
    assert ketamine.dose_mg_per_kg == 80.0


def test_delete_dosage_protocol_cascades(logged_in_client, db_session):
    protocol = make_dosage_protocol(
        db_session, drugs=[('A', 1.0, 1.0)],
    )
    drug_ids = [d.id for d in protocol.drugs]
    pid = protocol.id

    response = logged_in_client.post(
        f'/settings/dosage_protocol/{pid}/delete', follow_redirects=False,
    )
    assert response.status_code in (200, 302)
    db_session.expire_all()
    assert db_session.get(DosageProtocol, pid) is None
    remaining = db_session.scalars(
        select(DosageProtocolDrug).where(DosageProtocolDrug.id.in_(drug_ids))
    ).all()
    assert remaining == []


# ---------------------------------------------------------------------------
# Animal-side calculator + log dose
# ---------------------------------------------------------------------------

def test_dosage_calculator_modal_renders(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='DOSE-1')
    make_dosage_protocol(db_session, name='Protocol-Modal')
    response = logged_in_client.get(f'/animals/{animal.id}/dosage/modal')
    assert response.status_code == 200
    # Protocol picker should be on the page.
    assert b'Protocol-Modal' in response.data
    # Weight + date + (editable) time inputs present.
    assert b'name="weight_g"' in response.data
    assert b'name="date"' in response.data
    assert b'name="time"' in response.data
    # The time field defaults to "now" so the user only has to override
    # when back-filling; the field should carry today's hour.
    expected_hour = f'value="{datetime.now().strftime("%H")}'
    assert expected_hour.encode() in response.data


def test_calculate_dosage_returns_volume_table(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='DOSE-CALC')
    protocol = make_dosage_protocol(
        db_session, name='Calc-Protocol',
        drugs=[('Ketamine', 100.0, 100.0)],
    )
    response = logged_in_client.post(
        f'/animals/{animal.id}/dosage/calculate',
        data={
            'protocol': str(protocol.id),
            'weight_g': '25',
            'date': date.today().isoformat(),
        },
    )
    assert response.status_code == 200
    # 100 mg/kg @ 100 mg/mL on 25 g = 0.025 mL — rendered with 3-decimal
    # format in the table partial.
    assert b'0.025' in response.data
    assert b'Ketamine' in response.data


def test_log_dosage_creates_animal_event(logged_in_client, db_session):
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='DOSE-LOG')
    procedure = make_procedure(db_session, name='CFTS-Log')
    target = make_procedure_target(db_session, name='Target-Log')
    protocol = make_dosage_protocol(
        db_session, name='Log-Protocol',
        procedure=procedure, procedure_target=target,
        drugs=[('Ketamine', 100.0, 100.0), ('Xylazine', 10.0, 20.0)],
    )

    # Caller-provided time: ensure the route honors it rather than
    # silently overwriting with ``now`` — back-filling an injection is
    # the whole point of letting the field be editable.
    custom_time = time(8, 30)
    response = logged_in_client.post(
        f'/animals/{animal.id}/dosage/log',
        data={
            'protocol': str(protocol.id),
            'weight_g': '25',
            'date': date.today().isoformat(),
            'time': custom_time.strftime('%H:%M'),
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    db_session.expire_all()
    events = db_session.scalars(
        select(AnimalEvent).where(AnimalEvent.animal_id == animal.id)
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.procedure_id == procedure.id
    assert event.procedure_target_id == target.id
    # ``log_dosage`` marks the event completed on the date the user
    # picked — the calculator's whole point is to record a dose that
    # actually happened, not to schedule one.
    assert event.completion_date == date.today()

    # ``completion_time`` should be whatever the form supplied (not the
    # current wall clock).
    assert event.completion_time == custom_time

    notes = event.notes
    # Per-drug line with concentration + volume, one row per drug.
    assert '\n' in notes  # multi-line
    assert 'Ketamine' in notes
    assert 'Xylazine' in notes
    # Concentration must be in the note since protocols are editable —
    # we don't want a future protocol edit to invalidate the historical
    # record of what was actually administered.
    assert '100' in notes  # ketamine concentration mg/mL
    assert '20' in notes   # xylazine concentration mg/mL
    assert '0.025' in notes  # ketamine volume in mL


def test_edit_event_modal_prefills_existing_time(logged_in_client, db_session):
    """Round-trip: the time stored on an event should appear in the
    edit modal's ``completion_time`` input value. No timezone math on
    the way in or out — what got stored is what shows up."""
    species = make_species(db_session)
    animal = make_animal(db_session, species=species)
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    event = make_event(
        db_session, animal=animal, procedure=procedure,
        procedure_target=target, completion_date=date.today(),
    )
    event.completion_time = time(9, 7)
    db_session.commit()

    response = logged_in_client.get(f'/animals/events/{event.id}/edit_modal')
    assert response.status_code == 200
    # WTForms TimeField default format is HH:MM:SS; the HTML <input
    # type="time"> accepts that and renders HH:MM. Either is fine —
    # just check the hour:minute prefix made it into the value.
    assert b'value="09:07' in response.data


def test_update_event_can_change_completion_time(logged_in_client, db_session):
    """The animal-event edit form exposes ``completion_time`` so a user
    can correct or back-fill the clock time on any event, not just ones
    created by the dose logger."""
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id='TIME-EDIT')
    procedure = make_procedure(db_session)
    target = make_procedure_target(db_session)
    event = make_event(
        db_session, animal=animal, procedure=procedure,
        procedure_target=target,
        completion_date=date.today(),
    )

    new_time = time(14, 5)
    response = logged_in_client.post(
        f'/animals/events/{event.id}/update',
        data={
            'procedure': str(procedure.id),
            'procedure_target': str(target.id),
            'side': '',
            'scheduled_date': date.today().isoformat(),
            'completion_date': date.today().isoformat(),
            'completion_time': new_time.strftime('%H:%M'),
            'notes': '',
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    db_session.expire_all()
    refreshed = db_session.get(AnimalEvent, event.id)
    assert refreshed.completion_time == new_time
