from collections import Counter, defaultdict

from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from colony_manager.models import Study, Animal, AnimalEvent
from .. import db
from ..forms import StudyForm, AddToStudyForm, QuickAddToStudyForm, NoteForm
from .util import flash_form_errors, get_or_404, render_modal

studies_bp = Blueprint('studies', __name__)


# ---------------------------------------------------------------------------
# Study event-groups helpers
# ---------------------------------------------------------------------------

# Side ordering used within each (root procedure, target) panel. Sides
# not in this map come after Right; ``None`` sorts last as the empty
# string.
_SIDE_ORDER = {'Left': 0, 'Right': 1}

# Sentinel used as the "tag id" for events that carry no tags. Lets
# the same dict structure track tagged and untagged buckets uniformly.
_UNTAGGED = '__untagged__'
_UNTAGGED_LABEL = '(untagged)'


def _event_date(event):
    """The "happened on" date for an event — completion if present,
    else scheduled. Matches the convention used elsewhere in the app.
    """
    return event.completion_date or event.scheduled_date


def _root_procedure(procedure, cache):
    """Walk up ``procedure.parent`` until the chain ends; return the
    topmost ancestor (which may be ``procedure`` itself).

    *cache* is a shared ``{procedure_id: root_procedure}`` dict the
    caller threads through to avoid re-walking ancestors for events
    that share intermediate parents — SQLAlchemy's identity map
    already caches the parent lookups themselves, but we still want
    to skip the Python-side walk.
    """
    pid = procedure.id
    if pid in cache:
        return cache[pid]
    current = procedure
    while current.parent is not None:
        current = current.parent
    cache[pid] = current
    return current


def _leaf_path_from_root(procedure, root):
    """Return the procedure's ``name``-path relative to ``root``.

    * ``procedure is root`` → returns ``''`` (cell shows just the
      date — no sub-label needed).
    * Otherwise → ``' > '`` joined names from the level below the
      root down to the leaf, e.g.  ``'100 dB SPL, 1.4-2.8 kHz'`` or
      ``'STM > go-nogo'``.
    """
    if procedure.id == root.id:
        return ''
    parts = []
    current = procedure
    while current is not None and current.id != root.id:
        parts.append(current.name)
        current = current.parent
    return ' > '.join(reversed(parts))


def _build_event_groups(animals):
    """Build the per-(root procedure, target) panel structure.

    *animals* is the iterable of Animals to display (already sorted
    by the caller). One panel per (root procedure, target). Inside
    each panel, columns split by (side, tag); each cell holds a list
    of sub-procedure buckets so a "Noise exposure" panel can show
    "100 dB SPL: 2025-01-05" and "103 dB SPL: 2025-02-10" side-by-
    side for one animal without merging the dates into a single
    range that loses the dB context.

    Returns::

        [
          {
            'root_procedure': <AnimalProcedure>,
            'target': <AnimalProcedureTarget>,
            'columns': [
              {'side', 'tag', 'tag_label', 'key': (side, tag_key)},
              ...
            ],
            'sides_summary': [{'side', 'colspan'}, ...],
            'rows': [
              {
                'animal': <Animal>,
                'has_any': bool,
                'cells': {
                  (side, tag_key): [
                    {
                      'sub_label': '100 dB SPL, 1.4-2.8 kHz',  # '' if leaf == root
                      'count': N,
                      'min_date': date,
                      'max_date': date,
                    },
                    ...
                  ] or None
                },
              },
            ],
            'total_events': int,
            'animals_missing': int,
          },
        ]
    """
    root_cache = {}

    # Bucket events by (root_procedure_id, target_id) → ...
    groups_by_key = defaultdict(lambda: {
        'root_procedure': None,
        'target': None,
        # (animal_id, side, tag_key, sub_label) → [date, ...]
        'dates_by_subcell': defaultdict(list),
        # set of (side, tag_obj_or_None, tag_key)
        'columns_seen': set(),
        # set of animal_ids that had ≥1 event in this group
        'animals_with_event': set(),
        # set of underlying event ids (so total_events doesn't double-
        # count multi-tagged events)
        'event_ids': set(),
    })

    for animal in animals:
        for event in animal.events:
            root = _root_procedure(event.procedure, root_cache)
            gkey = (root.id, event.procedure_target_id)
            g = groups_by_key[gkey]
            g['root_procedure'] = root
            g['target'] = event.procedure_target
            g['animals_with_event'].add(animal.id)
            g['event_ids'].add(event.id)
            ev_date = _event_date(event)
            sub_label = _leaf_path_from_root(event.procedure, root)
            tags = list(event.tags) or [None]
            for tag in tags:
                if tag is None:
                    tag_key = _UNTAGGED
                else:
                    tag_key = tag.id
                g['columns_seen'].add((event.side, tag, tag_key))
                g['dates_by_subcell'][
                    (animal.id, event.side, tag_key, sub_label)
                ].append(ev_date)

    # Materialise + sort.
    groups = []
    for gkey, g in groups_by_key.items():
        def col_sort_key(col):
            side, tag, tag_key = col
            return (
                _SIDE_ORDER.get(side, 99),
                side or '',
                1 if tag is None else 0,
                tag.name if tag is not None else '',
            )

        sorted_cols = sorted(g['columns_seen'], key=col_sort_key)
        columns = [
            {
                'side': side,
                'tag': tag,
                'tag_label': _UNTAGGED_LABEL if tag is None else tag.name,
                'key': (side, tag_key),
            }
            for (side, tag, tag_key) in sorted_cols
        ]

        sides_summary = []
        for col in columns:
            if sides_summary and sides_summary[-1]['side'] == col['side']:
                sides_summary[-1]['colspan'] += 1
            else:
                sides_summary.append({'side': col['side'], 'colspan': 1})

        rows = []
        animals_missing = 0
        for animal in animals:
            cells = {}
            has_any = animal.id in g['animals_with_event']
            for col in columns:
                # Collect all sub_label buckets in this (animal, side,
                # tag_key) cell.
                buckets = []
                for (aid, side, tk, sub_label), dates in (
                    g['dates_by_subcell'].items()
                ):
                    if aid == animal.id and side == col['side'] and tk == col['key'][1]:
                        buckets.append({
                            'sub_label': sub_label,
                            'count': len(dates),
                            'min_date': min(dates),
                            'max_date': max(dates),
                        })
                # Sort sub-buckets: unlabeled (root itself) first,
                # then alphabetical by sub_label.
                buckets.sort(key=lambda b: (b['sub_label'] != '', b['sub_label']))
                cells[col['key']] = buckets if buckets else None
            if not has_any:
                animals_missing += 1
            rows.append({'animal': animal, 'has_any': has_any, 'cells': cells})

        groups.append({
            'root_procedure': g['root_procedure'],
            'target': g['target'],
            'columns': columns,
            'sides_summary': sides_summary,
            'rows': rows,
            'total_events': len(g['event_ids']),
            'animals_missing': animals_missing,
        })

    groups.sort(key=lambda gr: (
        gr['root_procedure'].display_name if gr['root_procedure'] else '',
        gr['target'].name if gr['target'] else '',
    ))

    # Attach a JSON-friendly payload for the Alpine-driven panel. The
    # template uses this to render the grid client-side so we can
    # hide/reorder tag columns with no round-trip.
    for g in groups:
        g['panel_json'] = _panel_to_json(g)
        # Stable per-panel persist key (study scope is added by the
        # template since the helper doesn't see the study).
        rp = g['root_procedure']
        tg = g['target']
        g['panel_key'] = (
            f"rp{rp.id if rp else 0}-tg{tg.id if tg else 0}"
        )
    return groups


def _panel_to_json(group):
    """Flatten a group dict into JSON-serialisable primitives so the
    template can pass it straight into ``x-data``.

    Dates become ISO strings. Tag keys are stringified (``_UNTAGGED``
    sentinel stays as-is) so they survive the JS round-trip as object
    keys / array values without ambiguity.
    """
    # Unique tag list (preserves the column ordering produced above —
    # untagged ends up last because of the column sort key).
    tag_order = []
    tag_label_by_key = {}
    for col in group['columns']:
        tk = col['key'][1]
        if tk not in tag_label_by_key:
            tag_label_by_key[tk] = col['tag_label']
            tag_order.append(tk)
    # Sides preserve their server-side order (Left, Right, ...).
    side_order = []
    for col in group['columns']:
        if col['side'] not in side_order:
            side_order.append(col['side'])

    def _iso_buckets(buckets):
        if not buckets:
            return None
        return [
            {
                'sub_label': b['sub_label'],
                'count': b['count'],
                'min_date': b['min_date'].isoformat(),
                'max_date': b['max_date'].isoformat(),
            }
            for b in buckets
        ]

    rows = []
    for row in group['rows']:
        cells = {}
        for col in group['columns']:
            side, tk = col['key']
            cells[f"{side or ''}|{tk}"] = _iso_buckets(row['cells'][col['key']])
        rows.append({
            'animal_id': row['animal'].id,
            'animal_display_id': row['animal'].display_id,
            'has_any': row['has_any'],
            'cells': cells,
        })

    return {
        'tags': [
            {'key': str(tk), 'label': tag_label_by_key[tk]}
            for tk in tag_order
        ],
        'sides': [s or '' for s in side_order],
        'rows': rows,
    }


def _find_shared_data_files(animals):
    """Return ``[(data_file, [animal, ...]), ...]`` for files whose
    ``events`` collection spans multiple of the given animals.

    Scope is intentionally limited to in-study animals — the study
    page is the context for review, and a file shared with animals
    *outside* the study is a different kind of issue.
    """
    animal_ids = {a.id for a in animals}
    animal_by_id = {a.id: a for a in animals}

    file_to_animals = defaultdict(set)
    files_by_id = {}
    for animal in animals:
        for event in animal.events:
            for f in event.data_files:
                files_by_id[f.id] = f
                file_to_animals[f.id].add(animal.id)

    shared = []
    for fid, hits in file_to_animals.items():
        if len(hits) < 2:
            continue
        in_study = hits & animal_ids
        if len(in_study) < 2:
            continue
        shared.append((
            files_by_id[fid],
            sorted([animal_by_id[aid] for aid in in_study],
                   key=lambda a: a.display_id),
        ))
    shared.sort(key=lambda pair: pair[0].name)
    return shared


@studies_bp.route('/')
def list_studies():
    studies = db.session.scalars(select(Study)).all()
    return render_template('studies.html', studies=studies)


@studies_bp.route('/<int:study_id>')
def view_study(study_id):
    study = get_or_404(Study, study_id)
    edit_form = StudyForm(obj=study)
    add_form = AddToStudyForm()
    # WTForms-SQLAlchemy's QuerySelectField expects a Query object on
    # ``.query``, not a Select. Use the legacy ``db.session.query(...)``
    # form rather than ``select(...)``; it's not the global Model.query
    # monkey-patch we're removing, just SQLAlchemy's session-level
    # Query API which remains supported in 2.0.
    add_form.animals.query = db.session.query(Animal).filter(
        Animal.custom_id != None  # noqa: E711  (SQL IS NOT NULL needs ``!=``)
    )

    if edit_form.data and edit_form.validate_on_submit():
        name_collision = db.session.scalars(
            select(Study).where(Study.name == edit_form.name.data)
        ).first()
        if edit_form.name.data != study.name and name_collision:
            flash('A study with this name already exists.', 'danger')
        else:
            study.name = edit_form.name.data
            study.description = edit_form.description.data
            db.session.commit()
            flash(f'Study "{study.name}" has been updated.', 'success')
        return redirect(url_for('studies.view_study', study_id=study.id))

    if request.method == 'POST' and not edit_form.validate_on_submit():
        flash_form_errors(edit_form, title="Error updating study")

    # --- Event matrix + shared-files data ---
    # Load each animal's events with their procedure / target / tags /
    # data_files eagerly so the matrix builder doesn't fan into one
    # query per event.
    animals = sorted(
        db.session.scalars(
            select(Animal)
            .where(Animal.studies.any(Study.id == study.id))
            .options(
                selectinload(Animal.events).options(
                    joinedload(AnimalEvent.procedure),
                    joinedload(AnimalEvent.procedure_target),
                    selectinload(AnimalEvent.tags),
                    selectinload(AnimalEvent.data_files),
                ),
            )
        ).all(),
        key=lambda a: a.display_id,
    )
    event_groups = _build_event_groups(animals)
    shared_files = _find_shared_data_files(animals)

    return render_template(
        'view_study.html', study=study,
        event_groups=event_groups, shared_files=shared_files,
    )


@studies_bp.route('/create', methods=['POST'])
def create_study():
    form = StudyForm()
    if form.validate_on_submit():
        study = Study(name=form.name.data, description=form.description.data)
        db.session.add(study)
        db.session.commit()
        flash('Study created successfully.', 'success')
    else:
        flash_form_errors(form, title="Study create failed")
    return redirect(url_for('studies.list_studies'))


@studies_bp.route('/<int:study_id>/update', methods=['POST'])
def update_study(study_id):
    study = get_or_404(Study, study_id)
    form = StudyForm(obj=study)
    if form.validate_on_submit():
        form.populate_obj(study)
        db.session.commit()
        flash('Study updated successfully.', 'success')
    else:
        flash_form_errors(form, title="Study update failed")
    return redirect(request.referrer or url_for('studies.list_studies'))


@studies_bp.route('/<int:study_id>/animals/add', methods=['POST'])
def add_study_animals(study_id):
    study = get_or_404(Study, study_id)
    form = AddToStudyForm()
    # See view_study for why this uses db.session.query(...) instead
    # of select(...).
    form.animals.query = db.session.query(Animal)
    if form.validate_on_submit():
        for animal in form.animals.data:
            study.animals.append(animal)
        db.session.commit()
        flash(f'{len(form.animals.data)} animals added to study "{study.name}".', 'success')
    else:
        flash_form_errors(form, title="Failed to add animals")
    return redirect(request.referrer or url_for('studies.view_study', study_id=study.id))


@studies_bp.route('/<int:study_id>/animals/<int:animal_id>/delete', methods=['POST'])
def remove_study_animal(study_id, animal_id):
    study = get_or_404(Study, study_id)
    animal = get_or_404(Animal, animal_id)
    if animal in study.animals:
        study.animals.remove(animal)
        db.session.commit()
        flash(f'Animal {animal.custom_id} removed from study.', 'success')
    else:
        flash(f'Animal {animal.custom_id} not found in study.', 'danger')
    return redirect(request.referrer or url_for('studies.view_study', study_id=study.id))


@studies_bp.route('/bulk_assign', methods=['POST'])
def bulk_assign_animals():
    """Add a list of animals (by ID) to a study in one shot.

    Posted from the Animal Overview bulk-action bar: ``study_id`` plus
    repeated ``animal_ids`` fields.
    """
    try:
        study_id = int(request.form.get('study_id') or 0)
    except (TypeError, ValueError):
        study_id = 0
    animal_ids = request.form.getlist('animal_ids', type=int)

    if not study_id or not animal_ids:
        flash('Pick a study and at least one animal.', 'warning')
        return redirect(request.referrer or url_for('animals.list_animals'))

    study = get_or_404(Study, study_id)
    existing = {a.id for a in study.animals}
    animals = db.session.scalars(
        select(Animal).where(Animal.id.in_(animal_ids))
    ).all()

    added = 0
    for animal in animals:
        if animal.id in existing:
            continue
        study.animals.append(animal)
        added += 1
    db.session.commit()

    skipped = len(animals) - added
    if added and skipped:
        flash(f'Added {added} animals to "{study.name}" ({skipped} already in study).', 'success')
    elif added:
        flash(f'Added {added} animals to "{study.name}".', 'success')
    else:
        flash(f'All selected animals were already in "{study.name}".', 'info')
    return redirect(request.referrer or url_for('animals.list_animals'))


@studies_bp.route('/add/<int:animal_id>', methods=['POST'])
def add_study_animal(animal_id):
    animal = get_or_404(Animal, animal_id)
    form = QuickAddToStudyForm()
    if form.validate_on_submit():
        study = form.study.data
        if animal not in study.animals:
            study.animals.append(animal)
            db.session.commit()
            flash(f'Animal {animal.custom_id} added to study "{study.name}".', 'success')
        else:
            flash(f'Animal {animal.custom_id} is already in study "{study.name}".', 'warning')
    else:
        flash_form_errors(form, title="Failed to quick-add animal:")
    return redirect(request.referrer or url_for('animals.list_animals'))

# --- Modal Routes ---
@studies_bp.route('/create_modal')
def create_study_modal():
    return render_modal(StudyForm(), label='Add Study',
                        submit_url=url_for('studies.create_study'))


@studies_bp.route('/<int:study_id>/edit_modal')
def edit_study_modal(study_id):
    study = get_or_404(Study, study_id)
    return render_modal(StudyForm(obj=study), item=study,
                        label=f'Edit Study {study.name}',
                        submit_url=url_for('studies.update_study', study_id=study.id))
