"""Aggregation queries backing the Analysis Scoreboard.

The scoreboard answers "what data has been analyzed, by whom, and how
recently?" for the ratable DataTypes (ABR, IHC/OHC counts, synaptograms,
…). It reads the rating columns the nightly ``flask data sync-rating`` job
maintains on ``Data`` — ``is_rated`` / ``rating_note`` (completeness),
``analyzed_by`` (who worked the analysis) and ``analyzed_at`` (when it was
last modified) — and rolls them up per DataType and per analyst.

Which DataTypes are "ratable" is decided the same way as
``routes/animals.py:list_unrated_data``: a description class that sets
``supports_rating = True``.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from colony_manager.datatypes import load_description_class
from colony_manager.models import Data, DataType


# Not fully rated = unrated or partial; a "partial" analysis flags itself in
# the note ("Partial — ..."). Mirrors the predicates in list_unrated_data.
_NOT_RATED = or_(Data.is_rated.is_(False), Data.is_rated.is_(None))
_PARTIAL = Data.rating_note.ilike('%partial%')


def ratable_datatypes(session: Session):
    """Return the ``DataType`` rows whose description class supports rating.

    A misconfigured/unresolvable ``description_class`` is skipped rather
    than raising, matching the tolerant behavior of the rating-review page.
    """
    dts = session.scalars(
        select(DataType)
        .where(DataType.description_class.isnot(None))
        .order_by(DataType.name)
    ).all()
    out = []
    for dt in dts:
        try:
            if load_description_class(dt.description_class).supports_rating:
                out.append(dt)
        except Exception:
            pass
    return out


def scoreboard_summary(session: Session, datatypes, *, datatype_id=None):
    """Per-DataType completion counts.

    ``datatypes`` is the list of ratable ``DataType`` rows (from
    :func:`ratable_datatypes`). Every one is represented in the result even
    when it has no files yet, so the PI sees the full set. ``datatype_id``
    optionally restricts the rollup to a single type.

    Returns a list of dicts (ordered as ``datatypes``)::

        {'datatype': DataType, 'total', 'analyzed', 'partial',
         'not_started', 'pct'}   # pct = analyzed / total, 0..100 int
    """
    if datatype_id is not None:
        datatypes = [dt for dt in datatypes if dt.id == datatype_id]
    ids = [dt.id for dt in datatypes]
    if not ids:
        return []

    rows = session.execute(
        select(
            Data.datatype_id,
            func.count().label('total'),
            func.count().filter(Data.is_rated.is_(True)).label('analyzed'),
            func.count().filter(_NOT_RATED, _PARTIAL).label('partial'),
        )
        .where(Data.datatype_id.in_(ids))
        .group_by(Data.datatype_id)
    ).all()
    by_id = {r.datatype_id: r for r in rows}

    summary = []
    for dt in datatypes:
        r = by_id.get(dt.id)
        total = r.total if r else 0
        analyzed = r.analyzed if r else 0
        partial = r.partial if r else 0
        summary.append({
            'datatype': dt,
            'total': total,
            'analyzed': analyzed,
            'partial': partial,
            'not_started': total - analyzed - partial,
            'pct': round(100 * analyzed / total) if total else 0,
        })
    return summary


def scoreboard_by_analyst(session: Session, datatypes, *, since=None):
    """Per-analyst rollup expanded from ``Data.analyzed_by``.

    Honors ``since`` (only files whose ``analyzed_at`` is on/after it).
    Returns a list of dicts ordered by most work first::

        {'user', 'total', 'by_type': {datatype_name: count}, 'last_active'}
    """
    ids = [dt.id for dt in datatypes]
    if not ids:
        return []
    names = {dt.id: dt.name for dt in datatypes}

    stmt = select(Data.datatype_id, Data.analyzed_by, Data.analyzed_at).where(
        Data.datatype_id.in_(ids),
        Data.analyzed_by.isnot(None),
    )
    if since is not None:
        stmt = stmt.where(Data.analyzed_at >= since)

    people: dict[str, dict] = {}
    for datatype_id, analyzed_by, analyzed_at in session.execute(stmt):
        name = names.get(datatype_id, str(datatype_id))
        for user in (analyzed_by or []):
            p = people.setdefault(
                user, {'user': user, 'total': 0, 'by_type': {}, 'last_active': None},
            )
            p['total'] += 1
            p['by_type'][name] = p['by_type'].get(name, 0) + 1
            if analyzed_at is not None and (
                p['last_active'] is None or analyzed_at > p['last_active']
            ):
                p['last_active'] = analyzed_at

    return sorted(people.values(), key=lambda p: (-p['total'], p['user']))


def recent_analyses(session: Session, datatypes, *, since=None, limit=25):
    """Most recently analyzed ``Data`` rows (by ``analyzed_at`` desc).

    Feeds the scoreboard's activity list. Rows with no ``analyzed_at`` are
    excluded (nothing to place on a timeline).
    """
    ids = [dt.id for dt in datatypes]
    if not ids:
        return []
    stmt = (
        select(Data)
        .where(Data.datatype_id.in_(ids), Data.analyzed_at.isnot(None))
        .order_by(Data.analyzed_at.desc())
    )
    if since is not None:
        stmt = stmt.where(Data.analyzed_at >= since)
    return session.scalars(stmt.limit(limit)).all()
