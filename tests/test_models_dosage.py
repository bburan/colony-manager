"""Tests for the DosageProtocol / DosageProtocolDrug models.

The protocol owns its drugs with ``cascade='all, delete-orphan'`` so
deleting a protocol must clear out its child rows — this is the easiest
way for the colony admin to drop a misconfigured cocktail without
leaving dangling rows behind.
"""
from sqlalchemy import select

from colony_manager.models import DosageProtocol, DosageProtocolDrug

from .factories import (
    make_dosage_protocol, make_procedure, make_procedure_target,
)


def test_protocol_persists_with_drugs(db_session):
    procedure = make_procedure(db_session, name='CFTS')
    target = make_procedure_target(db_session, name='Whole animal')
    protocol = make_dosage_protocol(
        db_session,
        name='Mouse: CFTS (ket/xyl)',
        procedure=procedure,
        procedure_target=target,
        drugs=[
            ('Ketamine', 100.0, 100.0),
            ('Xylazine', 10.0, 20.0),
        ],
    )

    fresh = db_session.get(DosageProtocol, protocol.id)
    assert fresh.name == 'Mouse: CFTS (ket/xyl)'
    assert fresh.procedure_id == procedure.id
    assert fresh.procedure_target_id == target.id
    assert [d.name for d in fresh.drugs] == ['Ketamine', 'Xylazine']
    # The order_by='position' relationship attribute should hold across
    # reload — important because the calculator iterates ``protocol.drugs``
    # to build the volume table.
    assert [d.position for d in fresh.drugs] == [0, 1]


def test_protocol_delete_cascades_to_drugs(db_session):
    protocol = make_dosage_protocol(
        db_session,
        drugs=[('A', 1.0, 1.0), ('B', 2.0, 2.0)],
    )
    drug_ids = [d.id for d in protocol.drugs]
    assert drug_ids  # sanity

    db_session.delete(protocol)
    db_session.commit()

    remaining = db_session.scalars(
        select(DosageProtocolDrug).where(DosageProtocolDrug.id.in_(drug_ids))
    ).all()
    assert remaining == []
