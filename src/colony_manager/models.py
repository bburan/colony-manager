from datetime import date, timedelta
import re
from statistics import mean

from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import (
    func, orm, UniqueConstraint, MetaData, Table, Column, Integer, String,
    ForeignKey, Text, Boolean, Date, Float, and_, or_
)
from sqlalchemy.orm import (declared_attr, declarative_base, relationship,
                            backref, scoped_session, sessionmaker)

Base = declarative_base(
    metadata=MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s"
        },
    ),
)

Base.session = scoped_session(sessionmaker())
Base.query = Base.session.query_property()


# --- Association Tables ---
study_animals = Table('study_animals', Base.metadata,
    Column('study_id', Integer, ForeignKey('study.id'), primary_key=True),
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True)
)

user_roles = Table('user_roles', Base.metadata,
    Column('user_id', Integer, ForeignKey('user.id'), primary_key=True),
    Column('role_id', Integer, ForeignKey('user_role.id'), primary_key=True)
)

animal_tags = Table('animal_tags', Base.metadata,
    Column('animal_id', Integer, ForeignKey('animal.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('animal_tag.id'), primary_key=True)
)

animal_event_tags = Table('animal_event_tags', Base.metadata,
    Column('animal_event_id', Integer, ForeignKey('animal_event.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('animal_event_tag.id'), primary_key=True)
)


class VersionedModel(Base):
    """Base model that automatically adds created and updated timestamps."""
    __abstract__ = True
    __versioned__ = {}

    @declared_attr
    def __tablename__(cls):
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', cls.__name__)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


class Species(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    animals = relationship('Animal', backref='species', lazy=True)
    cages = relationship('Cage', backref='species', lazy=True)

    @classmethod
    def count_active_cages(cls):
        return cls.session.query(
            Species.name,
            func.count(func.distinct(Cage.id))
        ) \
        .outerjoin(Species.animals) \
        .outerjoin(Animal.cage) \
        .filter(
            or_(
                Animal.termination_date.is_(None), # Animal is active
                Animal.id.is_(None)               # OR there are no animals at all
            )
        )\
        .group_by(Species.id)\
        .all()

    @classmethod
    def count_active_animals(cls):
        return cls.session.query(
            Species.name,
            func.count(func.distinct(Animal.id))
        ) \
        .outerjoin(Species.animals) \
        .filter(
            and_(
                Animal.termination_date.is_(None), # Animal is active
                Animal.custom_id.isnot(None)               # OR there are no animals at all
            )
        )\
        .group_by(Species.id)\
        .all()

    @classmethod
    def count_unprocessed_ears(cls):
        return cls.session.query(
            Species.name,
            func.count(func.distinct(Ear.id))
        ) \
        .outerjoin(Species.animals) \
        .outerjoin(Animal.ears) \
        .filter(
            and_(
                Ear.immunolabel_date.is_(None), # Ear is not processed
            )
        )\
        .group_by(Species.id)\
        .all()

    @classmethod
    def count_active_breeding_pairs(cls):
        return cls.session.query(
            Species.name,
            func.count(func.distinct(BreedingPair.id))
        ) \
        .outerjoin(Species.animals) \
        .outerjoin(BreedingPair, and_(Animal.id == BreedingPair.male_animal_id, BreedingPair.is_active == True)) \
        .group_by(Species.id) \
        .all()


class Source(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    animals = relationship('Animal', backref='source', lazy=True)

class NestedMixin:

    @property
    def display_name(self):
        if self.parent:
            return f'{self.parent.name} > {self.name}'
        return self.name

    @classmethod
    def get_ordered(cls):
        Parent = orm.aliased(cls)
        group_sort = func.coalesce(Parent.name, cls.name)
        return cls.session.query(cls). \
            outerjoin(Parent, cls.parent_id == Parent.id). \
            order_by(
                group_sort.asc(),
                cls.parent_id.desc(),
                cls.name.asc(),
            )

class AnimalProcedure(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey('animal_procedure.id'), nullable=True)

    subcategories = relationship(
        'AnimalProcedure',
        backref=backref('parent', remote_side=[id]),
        lazy='dynamic'
    )

    events = relationship('AnimalEvent', backref='procedure', lazy=True)

class AnimalProcedureTarget(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    events = relationship('AnimalEvent', backref='procedure_target', lazy=True)

class TerminationReason(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    animals = relationship('Animal', backref='termination_reason', lazy=True)

class Cage(VersionedModel):
    id = Column(Integer, primary_key=True)
    custom_id = Column(String(50), unique=True, nullable=False)
    notes = Column(Text, nullable=True)
    species_id = Column(Integer, ForeignKey('species.id', use_alter=True), nullable=False)
    animals = relationship('Animal', backref='cage', lazy='dynamic', cascade="all, delete-orphan")

    @property
    def sources(self):
        return sorted({a.source for a in self.animals})

    @property
    def is_active(self):
        return self.animals.filter_by(termination_date=None).count() > 0

    @property
    def sex(self):
        return sorted(set(a.sex for a in self.animals))

    @property
    def sex_symbol(self):
        result = sorted(set(a.sex_symbol for a in self.animals))
        if len(result) == 2:
            return '⚥'
        elif len(result) == 1:
            return result[0]
        return ''

    def age_display(self, unit='day'):
        ages = sorted(set(getattr(a, f'age_in_{unit}s') for a in self.animals))
        if len(ages) == 0:
            return 'N/A'
        elif len(ages) == 1:
            return f'{ages[0]:.1f} {unit}s'
        return f'{ages[0]:.1f} to {ages[-1]:.1f} {unit}s'

    @property
    def source_display(self):
        sources = set(a.source_display for a in self.animals)
        if len(sources) == 0:
            return 'N/A'
        return ', '.join(sorted(sources))


class AnimalTag(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    parent_id = Column(Integer, ForeignKey('animal_tag.id'), nullable=True)
    subtags = relationship(
        'AnimalTag',
        backref=backref('parent', remote_side=[id]),
        lazy='dynamic'
    )

    @property
    def display_name(self):
        if self.parent:
            return f'{self.parent.name} > {self.name}'
        return self.name

class Animal(VersionedModel):
    id = Column(Integer, primary_key=True)
    custom_id = Column(String(100), unique=True, nullable=True)
    cage_id = Column(Integer, ForeignKey('cage.id', use_alter=True), nullable=False)
    species_id = Column(Integer, ForeignKey('species.id', use_alter=True), nullable=False)
    sex = Column(String(10), nullable=False)
    dob = Column(Date, nullable=False)
    source_id = Column(Integer, ForeignKey('source.id', use_alter=True), nullable=True)
    breeding_pair_id = Column(Integer, ForeignKey('breeding_pair.id'), nullable=True)
    notes = Column(Text, nullable=True)
    termination_date = Column(Date, nullable=True)
    termination_reason_id = Column(Integer, ForeignKey('termination_reason.id', use_alter=True), nullable=True)
    events = relationship('AnimalEvent', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    ears = relationship('Ear', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    breeding_pair = relationship('BreedingPair', back_populates='offspring', foreign_keys=[breeding_pair_id])
    weights = relationship('WeightLog', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    feedings = relationship('FeedLog', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    tags = relationship('AnimalTag', secondary=animal_tags, backref='animals')

    @property
    def events_by_date(self):
        groups = {}
        for e in self.events:
            groups.setdefault(e.date, []).append(e)
        return dict((d, sorted(groups[d], key=lambda x: x.procedure.name)) for d in sorted(groups.keys()))

    @property
    def has_events(self):
        return self.events.count() > 0

    @property
    def event_due(self):
        return any(e.scheduled_date == date.today() and e.completion_date is None for e in self.events)

    @property
    def event_overdue(self):
        return any(e.scheduled_date < date.today() and e.completion_date is None for e in self.events)

    @property
    def last_event_date(self):
        last_event = self.events.filter_by(status='completed').order_by(AnimalEvent.completion_date.desc()).first()
        return last_event.completion_date if last_event else date.min

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
        return self.termination_date is None

    @property
    def sex_symbol(self):
        return '♀' if self.sex == 'female' else '♂'

    @property
    def source_display(self):
        return 'N/A' if self.source is None else self.source.name

    @property
    def scheduled_events(self):
        scheduled = [e for e in self.events if e.completion_date is None]
        return sorted(scheduled, key=lambda x: x.scheduled_date)

    @property
    def completed_events(self):
        completed = [e for e in self.events if e.completion_date is not None]
        return sorted(completed, key=lambda x: x.completion_date)

    def age_display(self, unit='day'):
        age = getattr(self, f'age_in_{unit}s')
        return f'{age:.1f} {unit}s'

    @property
    def display_id(self):
        if self.custom_id:
            return self.custom_id
        else:
            return f'Animal from {self.cage.custom_id}'

    @property
    def baseline_weight(self):
        '''
        Get the most recent baseline weight as the average of all weights consecutively marked as baseline.
        '''
        baselines = []
        for w in self.weights.filter(WeightLog.weight != None).order_by(WeightLog.date.desc()).all():
            if w.baseline:
                baselines.append(w)
            elif len(baselines) > 0:
                break
        if len(baselines) > 0:
            return mean(w.weight for w in baselines)
        else:
            return None

    def weight_feed_history(self):
        # When current_baseline is None, we are in accumulation mode. When we get to the first non-baseline weight, then we calculate the mean baseline weight and set that to current_baselinmean baseline weight and set that to current_baseline
        baselines = []
        current_baseline = None
        history = {}
        for w in self.weights.order_by(WeightLog.date).all():
            if w.weight is not None:
                if w.baseline:
                    current_baseline = None
                    baselines.append(w)
                    baseline_pct = None
                else:
                    if current_baseline is None:
                        current_baseline = mean(w.weight for w in baselines)
                        baselines = []
                    baseline_pct = int(round((w.weight / current_baseline) * 100))
            else:
                baseline_pct = None
            history[w.date] = {
                'weight': w.weight,
                'baseline_pct': baseline_pct,
                'notes': w.notes,
                'feed': {},
                'total_feed': 0,
                'baseline': w.baseline
            }

        for f in self.feedings.all():
            day = history.setdefault(f.date, {'weight': None, 'note': '', 'feed': {}, 'total_feed': 0, 'baseline_pct': None})
            day['feed'][f.feed_id] = f.quantity
            day['total_feed'] += (f.quantity * f.feed_type.weight)

        return dict(sorted(history.items(), key=lambda item: item[0], reverse=True))

    @classmethod
    def _get_recent_feeds(cls, days=7):
        today = date.today()


    @classmethod
    def get_daily_logs(cls, reference_date=None, before=0, after=0):
        """Returns animals paired with their weight logs from the last X days."""
        if reference_date is None:
            reference_date = date.today()

        start_date = reference_date - timedelta(days=before)
        end_date = reference_date + timedelta(days=after)
        total_days = (end_date - start_date).days + 1

        weights = cls.session.query(cls, WeightLog).join(WeightLog) \
            .filter(
            WeightLog.date >= start_date,
            WeightLog.date <= end_date,
            #WeightLog.weight.is_not(None),
            #WeightLog.baseline == False
        ).all()

        feeds = cls.session.query(cls, FeedLog).join(FeedLog) \
            .filter(
            FeedLog.date >= start_date,
            FeedLog.date <= end_date,
        ).all()

        if len(weights):
            w_animals, weights = zip(*weights)
        else:
            w_animals, weights = [], []

        if len(feeds):
            f_animals, feeds = zip(*feeds)
        else:
            f_animals, feeds = [], []

        animals = sorted(set(w_animals) | set(f_animals), key=lambda x: x.display_id)
        results = {a: [{'date': start_date + timedelta(days=i), 'weight': None, 'feeds': [], 'total_feed': 0} \
                       for i in range(total_days)] for a in animals}

        for weight in weights:
            ix = (weight.date - start_date).days
            if 0 <= ix < total_days:
                results[weight.animal][ix]['weight'] = weight

        for feed_log in feeds:
            ix = (feed_log.date - start_date).days
            if 0 <= ix < total_days:
                results[feed_log.animal][ix]['total_feed'] += (feed_log.feed_type.weight * feed_log.quantity)
                results[feed_log.animal][ix]['feeds'].append(feed_log)
                results[feed_log.animal][ix][feed_log.feed_type.name] = feed_log.quantity

        return results

class BreedingPair(VersionedModel):
    id = Column(Integer, primary_key=True)
    custom_id = Column(String(50), unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)
    male_animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    male = relationship('Animal', foreign_keys=[male_animal_id])
    female_animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    female = relationship('Animal', foreign_keys=[female_animal_id])
    is_active = Column(Boolean, default=True, nullable=False)
    litters = relationship('Litter', backref='breeding_pair', lazy='dynamic', cascade="all, delete-orphan")
    offspring = relationship('Animal', back_populates='breeding_pair', foreign_keys='Animal.breeding_pair_id')

class Litter(VersionedModel):
    id = Column(Integer, primary_key=True)
    breeding_pair_id = Column(Integer, ForeignKey('breeding_pair.id', use_alter=True), nullable=False)
    dob = Column(Date, nullable=False)
    pup_count = Column(Integer, nullable=False)
    wean_date = Column(Date, nullable=True)

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days

class Feed(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    weight = Column(Float, nullable=False)

class WeightLog(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id'), nullable=False)
    date = Column(Date)
    weight = Column(Float, nullable=True)
    notes = Column(Text)
    baseline = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint('animal_id', 'date'),
    )

class FeedLog(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id'), nullable=False)
    feed_id = Column(Integer, ForeignKey('feed.id'), nullable=False)
    date = Column(Date)
    quantity = Column(Integer, nullable=False)  # Number of pellets
    feed_type = relationship('Feed')

    @property
    def total_grams(self):
        return self.amount * self.feed_type.weight

    __table_args__ = (
        UniqueConstraint('animal_id', 'feed_id', 'date'),
    )

class AnimalEventTag(VersionedModel, NestedMixin):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    parent_id = Column(Integer, ForeignKey('animal_event_tag.id'), nullable=True)
    subtags = relationship(
        'AnimalEventTag',
        backref=backref('parent', remote_side=[id]),
        lazy='dynamic'
    )

    @property
    def display_name(self):
        if self.parent:
            return f'{self.parent.name} > {self.name}'
        return self.name

class AnimalEvent(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    procedure_id = Column(Integer, ForeignKey('animal_procedure.id', use_alter=True), nullable=False)
    procedure_target_id = Column(Integer, ForeignKey('animal_procedure_target.id', use_alter=True), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    completion_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    tags = relationship('AnimalEventTag', secondary=animal_event_tags, backref='animal_procedure')

    @property
    def status(self):
        if self.completion_date is not None: return 'complete'
        if self.scheduled_date < date.today(): return 'overdue'
        if self.scheduled_date == date.today(): return 'due'
        return ''

    @property
    def date(self):
        return self.scheduled_date if self.completion_date is None else self.completion_date

class ImmunolabelingPanel(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    reagents = relationship('Reagent', backref='panel', lazy='dynamic', cascade="all, delete-orphan")
    ears = relationship('Ear', backref='panel', lazy=True)

class Reagent(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    panel_id = Column(Integer, ForeignKey('immunolabeling_panel.id'), nullable=False)

class Ear(VersionedModel):
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animal.id', use_alter=True), nullable=False)
    side = Column(String(5), nullable=False)
    cryoprotection_date = Column(Date, nullable=True)
    dissection_date = Column(Date, nullable=True)
    immunolabel_date = Column(Date, nullable=True)
    panel_id = Column(Integer, ForeignKey('immunolabeling_panel.id', use_alter=True), nullable=True)
    notes = Column(Text, nullable=True)
    confocal_images = relationship('ConfocalImage', backref='ear', lazy=True)

    @property
    def full_display(self):
        return f'{self.animal.custom_id} {self.side}'

    def __eq__(self, other):
        if not isinstance(other, Ear): return NotImplemented
        return self.id == other.id

    def __lt__(self, other):
        if not isinstance(other, Ear): return NotImplemented
        return (self.animal.custom_id, self.side) < (other.animal.custom_id, other.side)

class ConfocalImageType(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    confocal_images = relationship('ConfocalImage', backref='image_type', lazy=True)

class ConfocalImage(VersionedModel):
    id = Column(Integer, primary_key=True)
    ear_id = Column(Integer, ForeignKey('ear.id', use_alter=True), nullable=False)
    frequency = Column(Float, nullable=False)
    image_type_id = Column(Integer, ForeignKey('confocal_image_type.id', use_alter=True), nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(String(150), nullable=True)

    @property
    def full_display(self):
        return f'{self.ear.full_display} {self.image_type.name} {self.frequency}'

class Study(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    animals = relationship('Animal', secondary=study_animals, lazy='dynamic', backref=backref('studies', lazy='dynamic'))


class UserRole(VersionedModel):
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class User(VersionedModel):
    id = Column(Integer, primary_key=True)
    first_name = Column(String(150), unique=False, nullable=False)
    last_name = Column(String(150), unique=False, nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(512))
    roles = relationship('UserRole', secondary='user_roles', backref=backref('users', lazy='dynamic'))
    active = Column(Boolean, default=False, nullable=False)
    admin = Column(Boolean, default=False, nullable=False)

    def is_admin(self):
        return self.admin

    @property
    def is_active(self):
        return self.active

    @property
    def is_authenticated(self):
        return self.is_active

    @property
    def is_anonymous(self):
        return False

    def set_password(self, password):
        """Creates a hashed version of the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks the provided password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        return f'{self.first_name} {self.last_name}'

    # Python 3 implicitly set __hash__ to None if we override __eq__ We set it
    # back to its default implementation
    __hash__ = object.__hash__

    def get_id(self):
        return str(self.id)

    def __eq__(self, other):
        if isinstance(other, User):
            return self.get_id() == other.get_id()
        return NotImplemented

    def __ne__(self, other):
        equal = self.__eq__(other)
        if equal is NotImplemented:
            return NotImplemented
        return not equal


orm.configure_mappers()
