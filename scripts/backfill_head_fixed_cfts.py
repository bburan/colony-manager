"""One-off: reassign head-fixed files to a ``CFTS (awake)`` event.

For every Data file whose name (or relative_path) contains
``head-fixed`` (case-insensitive), ensure it ends up linked to
exactly one ``AnimalEvent`` whose procedure is ``CFTS (awake)``
(under parent ``Physiology``).

Per-file algorithm:

1. Parse the side (``Left`` / ``Right``) from the filename. Skip if
   neither keyword is present.
2. Determine the animal:
   * If the file is already linked to any event, use that event's
     animal (preserves whatever the prior linkage knew).
   * Otherwise, use the first ``candidate_animals`` entry.
   * Skip if neither path yields an animal.
3. Determine the date from ``Data.date``. Skip if missing.
4. Look for an existing CFTS (awake) event for ``(animal, side,
   date)``. If found, that's the target event. Otherwise, create
   a new one with the supplied ``--target`` as its
   ``procedure_target``.
5. Reassign: link the file to the target event and unlink it from
   any *other* events (CFTS or not). Orphaned events left behind
   by reassignment are not deleted — that's a separate cleanup
   step.

Files that are already linked to exactly the right CFTS event (and
nothing else) are no-ops — counted in ``already_correct``.

Usage
-----

::

    docker compose exec web python -m scripts.backfill_head_fixed_cfts \\
        --target "Cortex"

    docker compose exec web python -m scripts.backfill_head_fixed_cfts \\
        --target "Cortex" --dry-run
"""
import argparse
import logging
import re
import sys

from sqlalchemy import or_, select

from colony_manager_gui import create_app, db


log = logging.getLogger(__name__)


_HEAD_FIXED_RE = re.compile(r'head[\s_-]*fixed', re.IGNORECASE)
_SIDE_RE = re.compile(r'\b(left|right)\b', re.IGNORECASE)


def _parse_side(text):
    """Return ``'Left'`` / ``'Right'`` if the text contains the keyword
    as a whole word; ``None`` otherwise.
    """
    m = _SIDE_RE.search(text)
    if not m:
        return None
    return m.group(1).capitalize()


def _resolve_procedure(session):
    """Look up the ``Physiology > CFTS (awake)`` procedure."""
    from colony_manager.models import AnimalProcedure

    parent = session.scalars(
        select(AnimalProcedure).where(
            AnimalProcedure.name == 'Physiology',
            AnimalProcedure.parent_id.is_(None),
        )
    ).first()
    if parent is None:
        log.error('No top-level AnimalProcedure named "Physiology".')
        return None
    child = session.scalars(
        select(AnimalProcedure).where(
            AnimalProcedure.name == 'CFTS (awake)',
            AnimalProcedure.parent_id == parent.id,
        )
    ).first()
    if child is None:
        log.error('No AnimalProcedure named "CFTS (awake)" under "Physiology".')
        return None
    return child


def _resolve_target(session, target_name):
    """Look up the procedure target by name."""
    from colony_manager.models import AnimalProcedureTarget

    target = session.scalars(
        select(AnimalProcedureTarget).where(
            AnimalProcedureTarget.name == target_name,
        )
    ).first()
    if target is None:
        log.error('No AnimalProcedureTarget named %r.', target_name)
    return target


def _candidate_files(session):
    """Return Data rows whose name or relative_path matches head-fixed.

    Postgres ILIKE for the cheap server-side filter, then the regex
    in Python catches ``head fixed`` / ``head_fixed`` etc.
    """
    from colony_manager.models import Data

    rough = session.scalars(
        select(Data).where(
            or_(
                Data.name.ilike('%head%fixed%'),
                Data.relative_path.ilike('%head%fixed%'),
            )
        )
    ).all()
    return [
        f for f in rough
        if _HEAD_FIXED_RE.search(f.name)
        or _HEAD_FIXED_RE.search(f.relative_path)
    ]


def _find_matching_cfts_event(session, procedure, animal, side, on_date):
    """Look up an existing CFTS (awake) event for the given tuple.

    Date match is either ``scheduled_date`` or ``completion_date``
    (mirrors how ``DataType.match_targets`` resolves events).
    """
    from colony_manager.models import AnimalEvent

    return session.scalars(
        select(AnimalEvent).where(
            AnimalEvent.animal_id == animal.id,
            AnimalEvent.procedure_id == procedure.id,
            AnimalEvent.side == side,
            or_(
                AnimalEvent.scheduled_date == on_date,
                AnimalEvent.completion_date == on_date,
            ),
        )
    ).first()


def backfill(target_name, dry_run=False):
    """Walk head-fixed files and ensure each is linked to a CFTS event.

    Returns a counts dict.
    """
    from colony_manager.models import AnimalEvent

    session = db.session
    counts = {
        'considered': 0,
        'already_correct': 0,
        'reused_existing_event': 0,
        'created_new_event': 0,
        'unlinked_old_events': 0,
        'skipped_no_side': 0,
        'skipped_no_animal': 0,
        'skipped_no_date': 0,
    }

    procedure = _resolve_procedure(session)
    if procedure is None:
        return counts
    target = _resolve_target(session, target_name)
    if target is None:
        return counts

    files = _candidate_files(session)
    log.info('Found %d Data row(s) matching head-fixed.', len(files))

    for f in files:
        counts['considered'] += 1
        label = f.relative_path or f.name

        # --- Side ---
        side = _parse_side(f'{f.name} {f.relative_path}')
        if side is None:
            counts['skipped_no_side'] += 1
            log.warning('  [SKIP] %s: no "left"/"right" in name.', label)
            continue

        # --- Animal: prefer existing event's animal over candidate ---
        existing_events = list(getattr(f, 'events', []) or [])
        if existing_events:
            animal = existing_events[0].animal
        elif f.candidate_animals:
            animal = f.candidate_animals[0]
        else:
            counts['skipped_no_animal'] += 1
            log.warning(
                '  [SKIP] %s has no candidate_animals and no event linkage.',
                label,
            )
            continue

        # --- Date ---
        event_date = f.date
        if event_date is None:
            counts['skipped_no_date'] += 1
            log.warning('  [SKIP] %s: no parsed date.', label)
            continue

        # --- Resolve target event: existing CFTS match (anywhere in DB,
        #     not just on this file) OR new event. ---
        target_event = _find_matching_cfts_event(
            session, procedure, animal, side, event_date,
        )
        if target_event is None:
            log.info(
                '  [CREATE] %s → AnimalEvent(animal=%s, side=%s, date=%s)',
                label, animal.display_id, side, event_date.isoformat(),
            )
            if not dry_run:
                target_event = AnimalEvent(
                    animal_id=animal.id,
                    procedure_id=procedure.id,
                    procedure_target_id=target.id,
                    side=side,
                    scheduled_date=event_date,
                    completion_date=event_date,
                )
                session.add(target_event)
                session.flush()  # populate event.id for m2m append
            counts['created_new_event'] += 1
        else:
            counts['reused_existing_event'] += 1

        # --- Reassign: file must end up linked to exactly target_event ---
        currently_linked = list(getattr(f, 'events', []) or [])

        # Detect the no-op case: only target_event is linked and we
        # found it via the lookup (not via creation).
        if (
            target_event is not None  # may still be None under dry_run+create
            and currently_linked == [target_event]
        ):
            counts['already_correct'] += 1
            # Roll back the create-vs-reuse bookkeeping: this file
            # didn't actually need our help.
            if counts['reused_existing_event'] > 0:
                counts['reused_existing_event'] -= 1
            continue

        if not dry_run:
            # Drop any link that isn't target_event.
            for e in currently_linked:
                if e is not target_event:
                    f.events.remove(e)
                    counts['unlinked_old_events'] += 1
                    log.info(
                        '  [UNLINK] %s from event %s (procedure %s)',
                        label, e.id, e.procedure.name,
                    )
            # Add target_event if not already present.
            if target_event is not None and target_event not in f.events:
                f.events.append(target_event)
                log.info('  [LINK]   %s → event %s', label, target_event.id)

    if not dry_run:
        session.commit()

    log.info(
        'Backfill %s — considered=%d already_correct=%d '
        'created_new_event=%d reused_existing_event=%d '
        'unlinked_old_events=%d skipped_no_side=%d skipped_no_animal=%d '
        'skipped_no_date=%d',
        'dry-run' if dry_run else 'done',
        counts['considered'], counts['already_correct'],
        counts['created_new_event'], counts['reused_existing_event'],
        counts['unlinked_old_events'], counts['skipped_no_side'],
        counts['skipped_no_animal'], counts['skipped_no_date'],
    )
    return counts


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s',
    )

    parser = argparse.ArgumentParser(
        description=(
            'Ensure every head-fixed Data file is linked to exactly '
            'one Physiology > CFTS (awake) AnimalEvent.'
        ),
    )
    parser.add_argument(
        '--target', metavar='NAME', required=True,
        help='AnimalProcedureTarget name (e.g. "Cortex"). Required '
             'because AnimalEvent.procedure_target_id is NOT NULL '
             'on newly-created events.',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Log what would happen without writing.',
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        counts = backfill(args.target, dry_run=args.dry_run)

    # Non-zero exit if a non-dry-run pass had work to do but didn't do
    # anything — catches misconfig (wrong target / procedure / parse).
    if (
        not args.dry_run
        and counts['considered'] > 0
        and counts['created_new_event'] == 0
        and counts['reused_existing_event'] == 0
        and counts['already_correct'] == 0
    ):
        sys.exit(2)
