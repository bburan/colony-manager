"""Animal-domain models.

Includes everything tightly coupled to the animal entity:
Species, Source, TerminationReason, AnimalProcedure/Target/Event/Tag,
DosageProtocol, Cage, Animal, BreedingPair, Litter,
Feed, WeightLog, FeedLog, and Study.

``Animal.terminate()`` creates ``Ear`` instances; it lazily imports
``Ear`` from ``.histology`` to avoid a circular import at module load
time.
"""
from datetime import date, datetime, timedelta
from statistics import mean

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, Time, UniqueConstraint,
)
from sqlalchemy.orm import backref, joinedload, relationship

from .base import (
    NestedMixin, VersionedModel,
    animal_event_tags, animal_tags, study_animals,
)


# ---------------------------------------------------------------------------
# Lookup / reference tables
# ---------------------------------------------------------------------------

class Species(VersionedModel):
    id      = Column(Integer, primary_key=True)
    name    = Column(String(100), unique=True, nullable=False)
    animals = relationship('Animal', backref='species', lazy=True)
    cages   = relationship('Cage',   backref='species', lazy=True)


class Source(VersionedModel):
    id      = Column(Integer, primary_key=True)
    name    = Column(String(100), unique=True, nullable=False)
    animals = relationship('Animal', backref='source', lazy=True)


class TerminationReason(VersionedModel):
    id      = Column(Integer, primary_key=True)
    name    = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    animals = relationship('Animal', backref='termination_reason', lazy=True)


# ---------------------------------------------------------------------------
# Procedure hierarchy
# ---------------------------------------------------------------------------

class AnimalProcedure(VersionedModel, NestedMixin):
    id          = Column(Integer, primary_key=True)
    name        = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    parent_id   = Column(Integer, ForeignKey('animal_procedure.id'), nullable=True)

    __table_args__ = (
        UniqueConstraint('parent_id', 'name', name='uq_animal_procedure_parent_id_name'),
        Index(
            'uq_animal_procedure_name_root',
            'name',
            unique=True,
            postgresql_where=Column('parent_id').is_(None),
            sqlite_where=Column('parent_id').is_(None),
        ),
    )

    subcategories = relationship(
        'AnimalProcedure',
        backref=backref('parent', remote_side=[id]),
    )
    events = relationship('AnimalEvent', backref='procedure', lazy=True)


class AnimalProcedureTarget(VersionedModel):
    id           = Column(Integer, primary_key=True)
    name         = Column(String(150), unique=True, nullable=False)
    description  = Column(Text, nullable=True)
    requires_side = Column(Boolean, nullable=False, default=False, server_default='false')
    events       = relationship('AnimalEvent', backref='procedure_target', lazy=True)


# ---------------------------------------------------------------------------
# Tag hierarchies
# ---------------------------------------------------------------------------

class AnimalTag(VersionedModel, NestedMixin):
    id        = Column(Integer, primary_key=True)
    name      = Column(String(150), nullable=False)
    parent_id = Column(Integer, ForeignKey('animal_tag.id'), nullable=True)
    subtags   = relationship('AnimalTag', backref=backref('parent', remote_side=[id]))
    __table_args__ = (UniqueConstraint('name', 'parent_id'),)


class AnimalEventTag(VersionedModel, NestedMixin):
    id        = Column(Integer, primary_key=True)
    name      = Column(String(150), nullable=False)
    parent_id = Column(Integer, ForeignKey('animal_event_tag.id'), nullable=True)
    subtags   = relationship('AnimalEventTag', backref=backref('parent', remote_side=[id]))
    __table_args__ = (UniqueConstraint('name', 'parent_id'),)


# ---------------------------------------------------------------------------
# Cage
# ---------------------------------------------------------------------------

class Cage(VersionedModel):
    id        = Column(Integer, primary_key=True)
    custom_id = Column(String(50), unique=True, nullable=False)
    notes     = Column(Text, nullable=True)
    species_id = Column(Integer, ForeignKey('species.id', use_alter=True), nullable=False)
    animals   = relationship('Animal', backref='cage', cascade='all, delete-orphan')

    @property
    def animals_count(self):
        return len(self.animals)

    @property
    def active_animals_count(self):
        return sum(1 for a in self.animals if a.termination_date is None)

    @property
    def is_active(self):
        return self.active_animals_count > 0

    @property
    def sex(self):
        return sorted({a.sex for a in self.animals})

    @property
    def sex_symbol(self):
        result = sorted({a.sex_symbol for a in self.animals})
        if len(result) == 2:
            return '⚥'
        elif len(result) == 1:
            return result[0]
        return ''

    def age_display(self, unit='day'):
        ages = sorted({getattr(a, f'age_in_{unit}s') for a in self.animals})
        if not ages:
            return 'N/A'
        elif len(ages) == 1:
            return f'{ages[0]:.1f} {unit}s'
        return f'{ages[0]:.1f} to {ages[-1]:.1f} {unit}s'

    @property
    def source_display(self):
        sources = {a.source_display for a in self.animals}
        if not sources:
            return 'N/A'
        return ', '.join(sorted(sources))


# ---------------------------------------------------------------------------
# Animal
# ---------------------------------------------------------------------------

class Animal(VersionedModel):
    id              = Column(Integer, primary_key=True)
    custom_id       = Column(String(100), unique=True, nullable=True)
    cage_id         = Column(Integer, ForeignKey('cage.id',    use_alter=True), nullable=False)
    species_id      = Column(Integer, ForeignKey('species.id', use_alter=True), nullable=False)
    sex             = Column(String(10), nullable=False)
    dob             = Column(Date, nullable=False)
    source_id       = Column(Integer, ForeignKey('source.id',  use_alter=True), nullable=True)
    breeding_pair_id = Column(Integer, ForeignKey('breeding_pair.id'), nullable=True)
    notes           = Column(Text, nullable=True)
    termination_date   = Column(Date, nullable=True)
    termination_reason_id = Column(
        Integer, ForeignKey('termination_reason.id', use_alter=True), nullable=True,
    )
    terminated = Column(Boolean, nullable=False, default=False, server_default='false')

    events   = relationship('AnimalEvent', backref='animal', cascade='all, delete-orphan')
    ears     = relationship('Ear',         backref='animal', cascade='all, delete-orphan')
    breeding_pair = relationship(
        'BreedingPair', back_populates='offspring',
        foreign_keys=[breeding_pair_id],
    )
    weights  = relationship('WeightLog', backref='animal', cascade='all, delete-orphan')
    feedings = relationship('FeedLog',   backref='animal', cascade='all, delete-orphan')
    tags     = relationship(
        'AnimalTag', secondary=animal_tags, backref='animals',
        order_by='AnimalTag.name',
    )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def events_by_date(self):
        groups = {}
        for e in self.events:
            groups.setdefault(e.date, []).append(e)
        return {d: sorted(groups[d], key=lambda x: x.procedure.name)
                for d in sorted(groups.keys())}

    @property
    def has_events(self):
        return bool(self.events)

    @property
    def events_count(self):
        return len(self.events)

    @property
    def studies_count(self):
        return len(self.studies)

    @property
    def event_due(self):
        return any(
            e.scheduled_date == date.today() and e.completion_date is None
            for e in self.events
        )

    @property
    def event_overdue(self):
        return any(
            e.scheduled_date < date.today() and e.completion_date is None
            for e in self.events
        )

    @property
    def last_event_date(self):
        completion_dates = [
            e.completion_date for e in self.events
            if e.completion_date is not None
        ]
        return max(completion_dates) if completion_dates else date.min

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days

    @property
    def age_in_weeks(self):
        return self.age_in_days / 7

    @property
    def age_in_months(self):
        return self.age_in_days / 30

    @property
    def is_active(self):
        return not self.terminated

    @property
    def sex_symbol(self):
        if self.sex == 'female':
            return '♀'
        elif self.sex == 'male':
            return '♂'
        return '?'

    @property
    def source_display(self):
        if self.breeding_pair:
            return self.breeding_pair.custom_id
        return 'N/A' if self.source is None else self.source.name

    @property
    def scheduled_events(self):
        return sorted(
            [e for e in self.events if e.completion_date is None],
            key=lambda x: x.scheduled_date,
        )

    @property
    def completed_events(self):
        return sorted(
            [e for e in self.events if e.completion_date is not None],
            key=lambda x: x.completion_date,
        )

    def terminate(self, termination_date=None, termination_reason=None,
                  ears_extracted=None):
        """Mark this animal as terminated and optionally create Ear records.

        Parameters
        ----------
        termination_date : date or None
        termination_reason : TerminationReason or None
        ears_extracted : ``'Left'`` | ``'Right'`` | ``'Both'`` | None

        Returns
        -------
        list[Ear]
        """
        if self.terminated:
            date_part = f' (on {self.termination_date})' if self.termination_date else ''
            raise ValueError(f'{self.display_id} is already terminated{date_part}.')

        valid_ear_choices = (None, 'Left', 'Right', 'Both')
        if ears_extracted not in valid_ear_choices:
            raise ValueError(
                f'ears_extracted must be one of {valid_ear_choices}, '
                f'got {ears_extracted!r}.'
            )

        self.terminated = True
        self.termination_date = termination_date
        self.termination_reason = termination_reason

        # Lazy import avoids the animal ↔ histology circular dependency.
        from .histology import Ear

        new_ears = []
        if ears_extracted in ('Left', 'Both'):
            new_ears.append(Ear(animal_id=self.id, side='Left'))
        if ears_extracted in ('Right', 'Both'):
            new_ears.append(Ear(animal_id=self.id, side='Right'))
        return new_ears

    def age_display(self, unit='day'):
        age = getattr(self, f'age_in_{unit}s')
        return f'{age:.1f} {unit}s'

    @property
    def display_id(self):
        if self.custom_id:
            return self.custom_id
        return f'Animal from {self.cage.custom_id}'

    @staticmethod
    def _baseline_from_weights(weights_desc):
        baselines = []
        for w in weights_desc:
            if w.weight is None:
                continue
            if w.baseline:
                baselines.append(w)
            elif baselines:
                break
        if baselines:
            return mean(w.weight for w in baselines)
        return None

    @property
    def baseline_weight(self):
        from .base import _MISSING
        cached = getattr(self, '_baseline_weight_cached', _MISSING)
        if cached is not _MISSING:
            return cached
        weights = sorted(
            (w for w in self.weights if w.weight is not None),
            key=lambda w: w.date,
            reverse=True,
        )
        return self._baseline_from_weights(weights)

    def weight_feed_history(self):
        baselines = []
        current_baseline = None
        history = {}
        for w in sorted(self.weights, key=lambda w: w.date):
            if w.weight is not None:
                if w.baseline:
                    current_baseline = None
                    baselines.append(w)
                    baseline_pct = None
                else:
                    if current_baseline is None and baselines:
                        current_baseline = mean(w.weight for w in baselines)
                        baselines = []
                    baseline_pct = (
                        int(round((w.weight / current_baseline) * 100))
                        if current_baseline is not None else None
                    )
            else:
                baseline_pct = None
            history[w.date] = {
                'weight': w.weight,
                'baseline_pct': baseline_pct,
                'notes': w.notes,
                'feed': {},
                'total_feed': 0,
                'baseline': w.baseline,
            }

        for f in self.feedings:
            day = history.setdefault(
                f.date,
                {'weight': None, 'note': '', 'feed': {}, 'total_feed': 0, 'baseline_pct': None},
            )
            day['feed'][f.feed_id] = f.quantity
            day['total_feed'] += (f.quantity * f.feed_type.weight)

        return dict(sorted(history.items(), key=lambda item: item[0], reverse=True))

    @classmethod
    def _get_recent_feeds(cls, days=7):
        today = date.today()

    @classmethod
    def get_daily_logs(cls, session, reference_date=None, before=0, after=0, species=None):
        """Return animals paired with their weight and feed logs over a date window."""
        from sqlalchemy import select

        if reference_date is None:
            reference_date = date.today()

        start_date = reference_date - timedelta(days=before)
        end_date   = reference_date + timedelta(days=after)
        total_days = (end_date - start_date).days + 1

        weight_stmt = select(cls, WeightLog).join(WeightLog).where(
            WeightLog.date >= start_date,
            WeightLog.date <= end_date,
        )
        feed_stmt = (
            select(cls, FeedLog)
            .join(FeedLog)
            .options(joinedload(FeedLog.feed_type))
            .where(FeedLog.date >= start_date, FeedLog.date <= end_date)
        )

        if species is not None:
            weight_stmt = weight_stmt.where(Animal.species == species)
            feed_stmt   = feed_stmt.where(Animal.species == species)

        weight_rows = session.execute(weight_stmt).all()
        feed_rows   = session.execute(feed_stmt).all()

        w_animals, weights = zip(*weight_rows) if weight_rows else ([], [])
        f_animals, feeds   = zip(*feed_rows)   if feed_rows   else ([], [])

        animals = sorted(set(w_animals) | set(f_animals), key=lambda x: x.display_id)

        if animals:
            animal_ids = [a.id for a in animals]
            by_animal = {a.id: [] for a in animals}
            baseline_rows = session.scalars(
                select(WeightLog)
                .where(
                    WeightLog.animal_id.in_(animal_ids),
                    WeightLog.weight.is_not(None),
                )
                .order_by(WeightLog.animal_id, WeightLog.date.desc())
            ).all()
            for w in baseline_rows:
                by_animal[w.animal_id].append(w)
            for a in animals:
                a._baseline_weight_cached = cls._baseline_from_weights(
                    by_animal.get(a.id, [])
                )

        results = {
            a: [
                {'date': start_date + timedelta(days=i),
                 'weight': None, 'feeds': [], 'total_feed': 0}
                for i in range(total_days)
            ]
            for a in animals
        }

        for weight in weights:
            ix = (weight.date - start_date).days
            if 0 <= ix < total_days:
                results[weight.animal][ix]['weight'] = weight

        for feed_log in feeds:
            ix = (feed_log.date - start_date).days
            if 0 <= ix < total_days:
                results[feed_log.animal][ix]['total_feed'] += (
                    feed_log.feed_type.weight * feed_log.quantity
                )
                results[feed_log.animal][ix]['feeds'].append(feed_log)
                results[feed_log.animal][ix][feed_log.feed_type.name] = feed_log.quantity

        return results


# ---------------------------------------------------------------------------
# Breeding
# ---------------------------------------------------------------------------

class BreedingPair(VersionedModel):
    id        = Column(Integer, primary_key=True)
    custom_id = Column(String(50), unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    notes     = Column(Text, nullable=True)

    male_animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    male = relationship('Animal', foreign_keys=[male_animal_id], backref='breeding_pair_male')

    female_animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    female = relationship('Animal', foreign_keys=[female_animal_id], backref='breeding_pair_female')

    is_active = Column(Boolean, default=True, nullable=False)
    litters   = relationship('Litter', backref='breeding_pair', cascade='all, delete-orphan')
    offspring = relationship(
        'Animal', back_populates='breeding_pair',
        foreign_keys='Animal.breeding_pair_id',
    )


class Litter(VersionedModel):
    id              = Column(Integer, primary_key=True)
    breeding_pair_id = Column(Integer, ForeignKey('breeding_pair.id', use_alter=True), nullable=False)
    dob             = Column(Date, nullable=False)
    pup_count       = Column(Integer, nullable=False)
    wean_date       = Column(Date, nullable=True)

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days


# ---------------------------------------------------------------------------
# Feeding / weight tracking
# ---------------------------------------------------------------------------

class Feed(VersionedModel):
    id     = Column(Integer, primary_key=True)
    name   = Column(String(50), unique=True, nullable=False)
    weight = Column(Float, nullable=False)


class WeightLog(VersionedModel):
    id        = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id'), nullable=False)
    date      = Column(Date)
    weight    = Column(Float, nullable=True)
    notes     = Column(Text)
    baseline  = Column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint('animal_id', 'date'),)


class FeedLog(VersionedModel):
    id        = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id'), nullable=False)
    feed_id   = Column(Integer, ForeignKey('feed.id'), nullable=False)
    date      = Column(Date)
    quantity  = Column(Integer, nullable=False)
    feed_type = relationship('Feed')

    @property
    def total_grams(self):
        return self.amount * self.feed_type.weight

    __table_args__ = (UniqueConstraint('animal_id', 'feed_id', 'date'),)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class AnimalEvent(VersionedModel):
    id                  = Column(Integer, primary_key=True)
    animal_id           = Column(Integer, ForeignKey('animal.id',               use_alter=True), nullable=False)
    procedure_id        = Column(Integer, ForeignKey('animal_procedure.id',      use_alter=True), nullable=False)
    procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id', use_alter=True), nullable=False)
    side                = Column(String(10), nullable=True)
    scheduled_date      = Column(Date, nullable=False)
    completion_date     = Column(Date, nullable=True)
    completion_time     = Column(Time, nullable=True)
    notes               = Column(Text, nullable=True)
    tags                = relationship(
        'AnimalEventTag', secondary=animal_event_tags,
        backref='animal_procedure', order_by='AnimalEventTag.name',
    )

    @property
    def status(self):
        if self.completion_date is not None:
            return 'complete'
        if self.scheduled_date < date.today():
            return 'overdue'
        if self.scheduled_date == date.today():
            return 'due'
        return ''

    @property
    def date(self):
        return self.scheduled_date if self.completion_date is None else self.completion_date

    @property
    def sorted_data_files(self):
        return sorted(self.data_files, key=lambda f: f.name)


# ---------------------------------------------------------------------------
# Dosage
# ---------------------------------------------------------------------------

class DosageProtocol(VersionedModel):
    """A reusable drug dosage protocol attached to a procedure."""
    id                  = Column(Integer, primary_key=True)
    name                = Column(String(150), unique=True, nullable=False)
    procedure_id        = Column(Integer, ForeignKey('animal_procedure.id',      use_alter=True), nullable=False)
    procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id', use_alter=True), nullable=False)
    notes               = Column(Text, nullable=True)

    procedure        = relationship('AnimalProcedure', lazy=True)
    procedure_target = relationship('AnimalProcedureTarget', lazy=True)
    drugs            = relationship(
        'DosageProtocolDrug',
        backref='protocol',
        cascade='all, delete-orphan',
        order_by='DosageProtocolDrug.position',
    )


class DosageProtocolDrug(VersionedModel):
    id                      = Column(Integer, primary_key=True)
    protocol_id             = Column(Integer, ForeignKey('dosage_protocol.id'), nullable=False)
    name                    = Column(String(100), nullable=False)
    dose_mg_per_kg          = Column(Float, nullable=False)
    concentration_mg_per_ml = Column(Float, nullable=False)
    position                = Column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Study
# ---------------------------------------------------------------------------

class Study(VersionedModel):
    id          = Column(Integer, primary_key=True)
    name        = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    animals     = relationship('Animal', secondary=study_animals, backref='studies')
