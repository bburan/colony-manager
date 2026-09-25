"""``Data.analyze`` — marking which replicate files staff should analyze.

Covers the three places the flag bites: the Needs Analysis queue and the
scoreboard (both via ``Data.in_analysis_queue``), the toggle route, and the
toggle's rendering, which is gated on the datatype supporting rating.
The histology grid's use of it lives with the rest of the conflict rule in
``test_confocal_conflict.py``.
"""
import re

import pytest
from sqlalchemy import select

from colony_manager.datatypes import reset_registry_cache
from colony_manager.enums import DataStatus
from colony_manager.models import AnimalData, Data

from .factories import make_animal, make_animal_data_type, make_data_location


@pytest.fixture(autouse=True)
def description_registry(monkeypatch):
    monkeypatch.setenv(
        'COLONY_MANAGER_DESCRIPTION_REGISTRY', 'tests._description_fakes',
    )
    reset_registry_cache()
    yield
    reset_registry_cache()


def _dtype(session, description_class='fake_ratable'):
    dtype = make_animal_data_type(session)
    dtype.description_class = description_class
    session.commit()
    return dtype


def _row(session, dtype, name, *, analyze=None, status=DataStatus.UNREVIEWED,
         is_rated=False, animal=None):
    loc = make_data_location(session, datatype=dtype, base_path=f'/tmp/{name}')
    row = AnimalData(
        datatype_id=dtype.id, location_id=loc.id, target_type='animal',
        relative_path=name, name=name, analyze=analyze, status=status,
        is_rated=is_rated, rating_note='Not analyzed',
    )
    if animal is not None:
        row.animals = [animal]
    session.add(row)
    session.commit()
    return row


def _seed_every_state(session, dtype):
    _row(session, dtype, 'notset.txt')
    _row(session, dtype, 'analyze.txt', analyze=True)
    _row(session, dtype, 'skipped.txt', analyze=False)
    _row(session, dtype, 'excluded.txt', status=DataStatus.EXCLUDE)
    _row(session, dtype, 'missing.txt', status=DataStatus.MISSING)


def test_in_analysis_queue_sql_matches_python(db_session):
    """The hybrid's SQL and instance forms must agree on every state."""
    dtype = _dtype(db_session)
    _seed_every_state(db_session, dtype)

    via_sql = set(db_session.scalars(
        select(Data.name).where(Data.in_analysis_queue)
    ))
    via_python = {r.name for r in db_session.scalars(select(Data)) if r.in_analysis_queue}
    assert via_sql == via_python == {'notset.txt', 'analyze.txt'}


def test_needs_analysis_drops_skipped_excluded_and_missing(logged_in_client, db_session):
    dtype = _dtype(db_session)
    _seed_every_state(db_session, dtype)

    resp = logged_in_client.get('/animals/unrated-data')
    assert resp.status_code == 200
    assert b'notset.txt' in resp.data
    assert b'analyze.txt' in resp.data
    assert b'skipped.txt' not in resp.data
    assert b'excluded.txt' not in resp.data
    assert b'missing.txt' not in resp.data


def test_scoreboard_summary_ignores_files_out_of_the_queue(db_session):
    from colony_manager_gui.services import data_queries

    dtype = _dtype(db_session)
    _seed_every_state(db_session, dtype)
    _row(db_session, dtype, 'done.txt', is_rated=True)
    # Analyzed but skipped: work that no longer counts either way.
    _row(db_session, dtype, 'done_skipped.txt', analyze=False, is_rated=True)

    (s,) = data_queries.scoreboard_summary(db_session, [dtype])
    assert s['total'] == 3            # notset, analyze, done
    assert s['analyzed'] == 1
    assert s['pct'] == 33


def test_analyze_defaults_to_not_set(db_session):
    """A new file is Not set — which the queue still treats as to-analyze."""
    dtype = _dtype(db_session)
    loc = make_data_location(db_session, datatype=dtype, base_path='/tmp/default')
    row = AnimalData(datatype_id=dtype.id, location_id=loc.id,
                     target_type='animal', relative_path='d.txt', name='d.txt')
    db_session.add(row)
    db_session.commit()
    assert row.analyze is None
    assert row.in_analysis_queue


@pytest.mark.parametrize('wire, stored', [('yes', True), ('no', False), ('', None)])
def test_set_analyze_round_trips(logged_in_client, db_session, wire, stored):
    row = _row(db_session, _dtype(db_session), 'f.txt',
               analyze=False if stored is not False else True)

    resp = logged_in_client.post(f'/animals/data/{row.id}/analyze', data={'analyze': wire})
    assert resp.status_code == 200
    body = resp.get_json()
    assert (body['status'], body['analyze']) == ('success', wire)
    db_session.expire_all()
    assert db_session.get(Data, row.id).analyze is stored


def test_set_analyze_rejects_unknown_value(logged_in_client, db_session):
    row = _row(db_session, _dtype(db_session), 'f.txt', analyze=False)
    resp = logged_in_client.post(f'/animals/data/{row.id}/analyze', data={'analyze': 'maybe'})
    assert resp.status_code == 400
    db_session.expire_all()
    assert db_session.get(Data, row.id).analyze is False


def test_set_analyze_refused_for_non_ratable_type(logged_in_client, db_session):
    row = _row(db_session, _dtype(db_session, 'fake_animal'), 'f.txt')
    resp = logged_in_client.post(f'/animals/data/{row.id}/analyze', data={'analyze': 'no'})
    assert resp.status_code == 400
    db_session.expire_all()
    assert db_session.get(Data, row.id).analyze is None


def test_set_analyze_404_for_unknown_file(logged_in_client):
    resp = logged_in_client.post('/animals/data/999999/analyze', data={'analyze': 'no'})
    assert resp.status_code == 404


def test_replicate_menu_only_for_ratable_types(logged_in_client, db_session):
    animal = make_animal(db_session)
    ratable = _row(db_session, _dtype(db_session), 'ratable.txt',
                   analyze=False, animal=animal)
    plain = _row(db_session, _dtype(db_session, 'fake_animal'), 'plain.txt',
                 animal=animal, is_rated=None)

    html = logged_in_client.get(f'/animals/{animal.id}').get_data(as_text=True)
    assert f'/animals/data/{ratable.id}/analyze' in html
    assert f'/animals/data/{plain.id}/analyze' not in html
    assert _badge(html, ratable.id) == 'Skipped'
    assert _badge(html, plain.id) is None


def test_badge_never_nests_inside_another_button(logged_in_client, db_session):
    """The badge is itself a <button> when it carries the menu; the file
    rows' own expand toggles are buttons too, and nesting them is invalid
    HTML."""
    animal = make_animal(db_session)
    dtype = _dtype(db_session)
    _row(db_session, dtype, 'copy1.txt', animal=animal)
    _row(db_session, dtype, 'copy2.txt', animal=animal)

    html = logged_in_client.get(f'/animals/{animal.id}').get_data(as_text=True)
    assert 'data-analyze-option' in html          # the menu really rendered
    depth = 0
    for tag in re.findall(r'<(/?)button\b', html):
        depth += -1 if tag else 1
        assert depth <= 1, 'a <button> opened inside another'


@pytest.mark.parametrize('analyze, active', [(None, ''), (True, 'yes'), (False, 'no')])
def test_menu_marks_the_current_choice(logged_in_client, db_session, analyze, active):
    """Every file of a ratable type gets the menu, replicate or not."""
    animal = make_animal(db_session)
    row = _row(db_session, _dtype(db_session), 'only.txt', analyze=analyze,
               is_rated=True, animal=animal)

    html = logged_in_client.get(f'/animals/{animal.id}').get_data(as_text=True)
    wrapper = _badge_html(html, row.id)[0]
    assert re.findall(r'data-analyze-option active"\s+data-set-analyze="(\w*)"', wrapper) == [active]
    assert re.findall(
        r'data-analyze-option[^>]*>([^<]*) <span class="df-analysis-hint">— ([^<]*)</span>',
        wrapper,
    ) == [
        ('Not set', 'no one has decided; will be analyzed'),
        ('Analyze', 'decided: analyze this file'),
        ('Skip', 'decided: no analysis needed'),
    ]
    # Only a deliberate Analyze carries the pin; Not set looks like any file.
    assert ('fa-thumbtack' in wrapper) == (analyze is True)


def test_menu_help_link_lands_on_the_section_explaining_it(logged_in_client, db_session):
    """The options have no inline hints; the link is the explanation, so a
    renamed heading must fail here rather than land on the page top."""
    from colony_manager_gui import helpdocs

    animal = make_animal(db_session)
    row = _row(db_session, _dtype(db_session), 'f.txt', animal=animal)
    html = logged_in_client.get(f'/animals/{animal.id}').get_data(as_text=True)
    (url,) = set(re.findall(r"openHelpModal\('(/help/[^']*)'\)", _badge_html(html, row.id)[0]))
    anchor = re.search(r'anchor=([\w-]+)', url).group(1)

    resp = logged_in_client.get(url)
    assert resp.status_code == 200
    assert f'id="{anchor}"' in resp.get_data(as_text=True)
    assert anchor == helpdocs.slugify('Not set, Analyze and Skip')


def _badge_html(html, data_id):
    """Every copy of a file's analysis-badge component on a page."""
    return re.findall(
        rf'<span class="df-analysis dropdown[^"]*" data-data-id="{data_id}">.*?</ul>\s*</span>'
        rf'|<span class="df-analysis dropdown[^"]*" data-data-id="{data_id}">\s*<span.*?</span>\s*</span>',
        html, re.S,
    )


def _badge(html, data_id):
    """The label of a file's analysis badge on a page, or None if absent."""
    labels = set()
    for chunk in _badge_html(html, data_id):
        inner = re.search(r'df-analysis-badge[^>]*>(.*?)</(?:button|span)>', chunk, re.S)
        labels.add(re.sub(r'<[^>]+>', '', inner.group(1)).strip())
    assert len(labels) <= 1, labels     # every copy on the page agrees
    return labels.pop() if labels else None


@pytest.mark.parametrize('fields, label', [
    ({'is_rated': True, 'rating_note': 'Done'}, 'Analyzed'),
    ({'is_rated': False, 'rating_note': 'Partial — no spiral for OHC1'}, 'Partial'),
    ({'is_rated': False, 'rating_note': 'Not analyzed'}, 'Not analyzed'),
    ({'is_rated': None, 'rating_note': None}, 'Unchecked'),
    # Skip wins over the rating: the file is out of the queue either way.
    ({'is_rated': True, 'analyze': False}, 'Skipped'),
])
def test_analysis_badge_states(logged_in_client, db_session, fields, label):
    animal = make_animal(db_session)
    row = _row(db_session, _dtype(db_session), 'f.txt', animal=animal)
    for k, v in fields.items():
        setattr(row, k, v)
    db_session.commit()

    html = logged_in_client.get(f'/animals/{animal.id}').get_data(as_text=True)
    assert _badge(html, row.id) == label


def test_set_analyze_returns_the_rerendered_badge(logged_in_client, db_session):
    row = _row(db_session, _dtype(db_session), 'f.txt', is_rated=True)

    skipped = logged_in_client.post(
        f'/animals/data/{row.id}/analyze', data={'analyze': 'no'}).get_json()
    assert _badge(skipped['indicator'], row.id) == 'Skipped'

    undone = logged_in_client.post(
        f'/animals/data/{row.id}/analyze', data={'analyze': 'yes'}).get_json()
    assert _badge(undone['indicator'], row.id) == 'Analyzed'


# ---------------------------------------------------------------------------
# Confocal files on a Poor histology / Region missing image
# ---------------------------------------------------------------------------

def _confocal_file(session, *, image_status, is_rated=False, analyzed_by=None,
                   analyzed_at=None, name=None):
    """A ratable confocal file linked to a fresh image with *image_status*."""
    from .factories import (
        make_confocal_image, make_confocal_image_data,
        make_confocal_image_data_type, make_ear,
    )
    ear = make_ear(session, animal=make_animal(session), side='Left')
    image = make_confocal_image(session, ear=ear)
    image.status = image_status
    dtype = make_confocal_image_data_type(session)
    dtype.description_class = 'fake_ratable'
    row = make_confocal_image_data(session, datatype=dtype, confocal_image=image)
    if name:
        row.name = row.relative_path = name
    row.is_rated = is_rated
    row.rating_note = 'Done' if is_rated else 'Not analyzed'
    row.analyzed_by = analyzed_by
    row.analyzed_at = analyzed_at
    session.commit()
    return row


@pytest.mark.parametrize('image_status, queued', [
    ('imaged', True),
    ('analyzed', True),
    ('need_review', True),
    (None, True),                  # NULL reads as imaged
    ('region_bad', False),
    ('region_missing', False),
])
def test_image_status_decides_queue_membership(db_session, image_status, queued):
    row = _confocal_file(db_session, image_status=image_status)
    assert row.in_analysis_queue is queued
    in_sql = db_session.scalars(
        select(Data.id).where(Data.id == row.id, Data.in_analysis_queue)
    ).first() is not None
    assert in_sql is queued


def test_needs_analysis_drops_poor_histology(logged_in_client, db_session):
    _confocal_file(db_session, image_status='region_bad', name='poor.czi')
    _confocal_file(db_session, image_status='imaged', name='good.czi')

    resp = logged_in_client.get('/animals/unrated-data')
    assert b'good.czi' in resp.data
    assert b'poor.czi' not in resp.data


def test_poor_histology_is_off_every_scoreboard_panel(db_session):
    """Even when analyzed: the region isn't usable, so the work isn't owed
    and isn't credited."""
    from datetime import datetime
    from colony_manager_gui.services import data_queries

    when = datetime(2026, 9, 1)
    poor = _confocal_file(db_session, image_status='region_bad', is_rated=True,
                          analyzed_by=['Sean'], analyzed_at=when)
    good = _confocal_file(db_session, image_status='analyzed', is_rated=True,
                          analyzed_by=['Brad'], analyzed_at=when)
    dtypes = [poor.datatype, good.datatype]

    summary = {s['datatype'].id: s for s in data_queries.scoreboard_summary(db_session, dtypes)}
    assert summary[poor.datatype_id]['total'] == 0
    assert summary[good.datatype_id]['total'] == 1

    analysts = {p['user'] for p in data_queries.scoreboard_by_analyst(db_session, dtypes)}
    assert analysts == {'Brad'}

    recent = data_queries.recent_analyses(db_session, dtypes)
    assert [r.id for r in recent] == [good.id]


@pytest.mark.parametrize('image_status, label', [
    ('region_bad', 'Poor histology'),
    ('region_missing', 'Region missing'),
])
def test_badge_names_the_image_status_and_offers_no_menu(
    logged_in_client, db_session, image_status, label,
):
    row = _confocal_file(db_session, image_status=image_status, is_rated=True)
    ear = row.confocal_images[0].ear

    html = logged_in_client.get(f'/histology/ears/{ear.id}').get_data(as_text=True)
    assert _badge(html, row.id) == label
    (wrapper,) = set(_badge_html(html, row.id))
    assert 'data-analyze-option' not in wrapper
