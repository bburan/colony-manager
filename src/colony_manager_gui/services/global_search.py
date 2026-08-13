"""Cross-entity typeahead search backing the navbar 'jump to' box.

Adding a new searchable entity type means one more block in
:func:`search` (query + result-building) plus a route entry in
``main.py``'s ``_SEARCH_ROUTES`` — no changes to the navbar/JS.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from colony_manager.models import Animal, Cage, Ear, Study

# Trailing/leading words that disambiguate which entity type the user
# means, e.g. "G020-1 cage" or "G020-1 ear left". Stripped out of the
# query before it's used as the id/name substring match.
_KIND_WORDS = {
    'animal': 'animal', 'animals': 'animal',
    'cage': 'cage', 'cages': 'cage',
    'study': 'study', 'studies': 'study',
    'ear': 'ear', 'ears': 'ear',
}
_SIDE_WORDS = {'left': 'Left', 'right': 'Right'}


@dataclass
class SearchResult:
    kind: str  # 'animal' | 'cage' | 'study' | 'ear' — see main.py:_SEARCH_ROUTES
    id: int
    label: str
    sublabel: str | None = None


def _parse_query(q: str) -> tuple[str, str | None, str | None]:
    """Split a kind/side hint word off the query, if present.

    'G020-1 cage'      -> ('G020-1', 'cage', None)
    'G020-1 ear left'  -> ('G020-1', 'ear', 'Left')
    'G020-1 left'      -> ('G020-1', 'ear', 'Left')   -- 'left'/'right' imply ear
    'G020-1'           -> ('G020-1', None, None)

    A lone word is never treated as a hint (a cage genuinely named
    "Cage9" must still be findable by typing just that). Likewise, if
    every word in a multi-word query turns out to be a hint word ("cage
    left", nothing else), there's no id text left to match against — fall
    back to searching on the raw query instead of returning nothing.
    """
    tokens = q.split()
    if len(tokens) < 2:
        return q, None, None

    kind = None
    side = None
    remaining = []
    for tok in tokens:
        low = tok.lower()
        if kind is None and low in _KIND_WORDS:
            kind = _KIND_WORDS[low]
        elif side is None and low in _SIDE_WORDS:
            side = _SIDE_WORDS[low]
        else:
            remaining.append(tok)

    id_query = ' '.join(remaining).strip()
    if not id_query:
        return q, None, None
    if side and kind is None:
        kind = 'ear'
    return id_query, kind, side


def search(session: Session, q: str, *, limit: int = 6) -> list[SearchResult]:
    """Case-insensitive substring match across Animal/Cage/Study/Ear.

    A trailing kind word ('cage', 'study', 'ear') or, for ears, a side
    word ('left'/'right') narrows the search to just that entity type —
    see :func:`_parse_query`. Without one, all four types are searched
    and returned grouped in that order (animals first — the most common
    lookup), up to ``limit`` matches each. Narrowing to one type also
    means only that one query runs, instead of all four.

    Empty/whitespace ``q`` returns ``[]`` so the dropdown stays empty
    until the user types.
    """
    q = (q or '').strip()
    if not q:
        return []
    id_query, kind, side = _parse_query(q)
    pattern = f'%{id_query}%'
    results: list[SearchResult] = []

    if kind in (None, 'animal'):
        animals = session.scalars(
            select(Animal)
            .where(Animal.custom_id.ilike(pattern))
            .options(joinedload(Animal.species))
            .order_by(Animal.custom_id)
            .limit(limit)
        ).all()
        results += [
            SearchResult('animal', a.id, a.custom_id, a.species.name)
            for a in animals
        ]

    if kind in (None, 'cage'):
        cages = session.scalars(
            select(Cage)
            .where(Cage.custom_id.ilike(pattern))
            .order_by(Cage.custom_id)
            .limit(limit)
        ).all()
        results += [SearchResult('cage', c.id, c.custom_id, 'Cage') for c in cages]

    if kind in (None, 'study'):
        studies = session.scalars(
            select(Study)
            .where(Study.name.ilike(pattern))
            .order_by(Study.name)
            .limit(limit)
        ).all()
        results += [SearchResult('study', s.id, s.name, 'Study') for s in studies]

    if kind in (None, 'ear'):
        stmt = (
            select(Ear)
            .join(Animal, Ear.animal_id == Animal.id)
            .where(Animal.custom_id.ilike(pattern))
            .options(joinedload(Ear.animal))
        )
        if side:
            stmt = stmt.where(Ear.side == side)
        ears = session.scalars(
            stmt.order_by(Animal.custom_id, Ear.side).limit(limit)
        ).all()
        results += [
            SearchResult('ear', e.id, f'{e.animal.custom_id} — {e.side}', 'Ear')
            for e in ears
        ]

    return results
