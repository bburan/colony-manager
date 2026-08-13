"""Unit tests for colony_manager_gui.services.global_search.

Exercises the cross-entity match logic directly against the DB —
each entity type's ilike-substring match, the empty-query short
circuit, that an unmatched query returns [] rather than raising, and
the kind/side disambiguation words ('cage', 'ear', 'left', 'right').
"""
from colony_manager.models import Study
from colony_manager_gui.services.global_search import search

from .factories import make_animal, make_cage, make_ear, make_species


def test_empty_query_returns_no_results(db_session):
    make_animal(db_session, custom_id='GS-1')
    assert search(db_session, '') == []
    assert search(db_session, '   ') == []


def test_matches_animal_by_custom_id_substring(db_session):
    species = make_species(db_session, name='Gerbil')
    make_animal(db_session, species=species, custom_id='GS-ANIMAL-1')

    results = search(db_session, 'gs-animal')

    assert len(results) == 1
    result = results[0]
    assert result.kind == 'animal'
    assert result.label == 'GS-ANIMAL-1'
    assert result.sublabel == 'Gerbil'


def test_matches_cage_by_custom_id_substring(db_session):
    cage = make_cage(db_session, custom_id='GS-CAGE-1')

    results = search(db_session, 'gs-cage')

    assert len(results) == 1
    assert results[0].kind == 'cage'
    assert results[0].id == cage.id
    assert results[0].label == 'GS-CAGE-1'


def test_matches_study_by_name_substring(db_session):
    study = Study(name='GS Study Alpha')
    db_session.add(study)
    db_session.commit()

    results = search(db_session, 'study alpha')

    assert len(results) == 1
    assert results[0].kind == 'study'
    assert results[0].id == study.id
    assert results[0].label == 'GS Study Alpha'


def test_matches_ear_by_parent_animal_custom_id(db_session):
    animal = make_animal(db_session, custom_id='GS-EAR-1')
    ear = make_ear(db_session, animal=animal, side='Left')

    results = search(db_session, 'gs-ear')

    # The animal itself also matches on the same substring — that's
    # expected, not a bug in the test.
    ear_results = [r for r in results if r.kind == 'ear']
    assert len(ear_results) == 1
    assert ear_results[0].id == ear.id
    assert ear_results[0].label == 'GS-EAR-1 — Left'


def test_query_with_no_matches_returns_empty_list(db_session):
    make_animal(db_session, custom_id='GS-2')
    assert search(db_session, 'no-such-id-anywhere') == []


def test_results_are_grouped_animal_cage_study_ear(db_session):
    """Different entity types sharing a matchable substring all come back,
    in a stable animal/cage/study/ear order (the navbar UI relies on this
    for a predictable 'first result' when the user hits Enter).
    """
    species = make_species(db_session)
    make_animal(db_session, species=species, custom_id='SHARED-1')
    make_cage(db_session, custom_id='SHARED-CAGE')
    study = Study(name='SHARED Study')
    db_session.add(study)
    db_session.commit()
    other_animal = make_animal(db_session, species=species, custom_id='SHARED-2')
    make_ear(db_session, animal=other_animal, side='Right')

    results = search(db_session, 'shared')

    kinds = [r.kind for r in results]
    assert kinds == sorted(kinds, key=['animal', 'cage', 'study', 'ear'].index)
    assert {'animal', 'cage', 'study', 'ear'} <= set(kinds)


# ---------------------------------------------------------------------------
# Kind/side disambiguation words
# ---------------------------------------------------------------------------

def _make_ambiguous_fixtures(db_session, tag):
    """An animal, cage, and study that all share a substring, plus an
    ear on that animal — so a plain (unqualified) search for ``tag``
    would otherwise match all four.
    """
    species = make_species(db_session)
    animal = make_animal(db_session, species=species, custom_id=f'{tag}-1')
    cage = make_cage(db_session, custom_id=f'{tag}-1')
    study = Study(name=f'{tag}-1 Study')
    db_session.add(study)
    db_session.commit()
    ear = make_ear(db_session, animal=animal, side='Left')
    return animal, cage, study, ear


def test_cage_keyword_disambiguates_to_cage_only(db_session):
    animal, cage, study, ear = _make_ambiguous_fixtures(db_session, 'AMBIG1')

    results = search(db_session, 'AMBIG1-1 cage')

    assert [r.kind for r in results] == ['cage']
    assert results[0].id == cage.id


def test_animal_keyword_disambiguates_to_animal_only(db_session):
    animal, cage, study, ear = _make_ambiguous_fixtures(db_session, 'AMBIG2')

    results = search(db_session, 'AMBIG2-1 animal')

    assert [r.kind for r in results] == ['animal']
    assert results[0].id == animal.id


def test_study_keyword_disambiguates_to_study_only(db_session):
    animal, cage, study, ear = _make_ambiguous_fixtures(db_session, 'AMBIG3')

    results = search(db_session, 'AMBIG3-1 study')

    assert [r.kind for r in results] == ['study']
    assert results[0].id == study.id


def test_ear_keyword_disambiguates_to_ear_only(db_session):
    animal, cage, study, ear = _make_ambiguous_fixtures(db_session, 'AMBIG4')

    results = search(db_session, 'AMBIG4-1 ear')

    assert [r.kind for r in results] == ['ear']
    assert results[0].id == ear.id


def test_side_word_implies_ear_without_explicit_ear_keyword(db_session):
    animal, cage, study, ear = _make_ambiguous_fixtures(db_session, 'AMBIG5')

    results = search(db_session, 'AMBIG5-1 left')

    assert [r.kind for r in results] == ['ear']
    assert results[0].id == ear.id


def test_side_word_filters_by_side(db_session):
    animal = make_animal(db_session, custom_id='AMBIG6-1')
    left_ear = make_ear(db_session, animal=animal, side='Left')
    right_ear = make_ear(db_session, animal=animal, side='Right')

    results = search(db_session, 'AMBIG6-1 right')

    assert [r.id for r in results] == [right_ear.id]


def test_kind_and_side_words_are_case_insensitive(db_session):
    animal, cage, study, ear = _make_ambiguous_fixtures(db_session, 'AMBIG7')

    results = search(db_session, 'AMBIG7-1 CAGE')
    assert [r.kind for r in results] == ['cage']

    results = search(db_session, 'AMBIG7-1 Left')
    assert [r.kind for r in results] == ['ear']


def test_bare_keyword_is_not_treated_as_a_hint(db_session):
    """A single-word query is never stripped of a hint word — a cage
    that's literally named 'Cage9' must still be findable by typing
    just that.
    """
    cage = make_cage(db_session, custom_id='Cage9')
    results = search(db_session, 'Cage9')
    assert [r.kind for r in results] == ['cage']
    assert results[0].id == cage.id


def test_all_keyword_tokens_falls_back_to_raw_query(db_session):
    """If every word in the query is a hint word ('cage left'), there's
    no id text left to filter on — fall back to matching the raw query
    across all types instead of silently returning nothing.
    """
    cage = make_cage(db_session, custom_id='cage left')
    results = search(db_session, 'cage left')
    assert any(r.id == cage.id and r.kind == 'cage' for r in results)
