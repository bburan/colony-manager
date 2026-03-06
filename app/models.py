from datetime import date, timedelta
from statistics import mean

from sqlalchemy import func, orm, UniqueConstraint
from app import db
from flask_login import current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


# --- Association Tables ---
study_animals = db.Table('study_animals',
    db.Column('study_id', db.Integer, db.ForeignKey('study.id'), primary_key=True),
    db.Column('animal_id', db.Integer, db.ForeignKey('animal.id'), primary_key=True)
)

user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('user_role.id'), primary_key=True)
)

class VersionedModel(db.Model):
    """Base model that automatically adds created and updated timestamps."""
    __abstract__ = True
    __versioned__ = {}

class UserRole(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class User(UserMixin, VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(150), unique=False, nullable=False)
    last_name = db.Column(db.String(150), unique=False, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(512))
    roles = db.relationship('UserRole', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    active = db.Column(db.Boolean, default=False, nullable=False)
    admin = db.Column(db.Boolean, default=False, nullable=False)

    def is_admin(self):
        return self.admin

    def is_active(self):
        return self.active

    def set_password(self, password):
        """Creates a hashed version of the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks the provided password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        return f'{self.first_name} {self.last_name}'

class Species(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='species', lazy=True)
    cages = db.relationship('Cage', backref='species', lazy=True)

class Source(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    animals = db.relationship('Animal', backref='source', lazy=True)

class AnimalProcedure(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    events = db.relationship('AnimalEvent', backref='procedure', lazy=True)

class AnimalProcedureTarget(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    events = db.relationship('AnimalEvent', backref='procedure_target', lazy=True)

class TerminationReason(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    animals = db.relationship('Animal', backref='termination_reason', lazy=True)

class Cage(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id', use_alter=True), nullable=False)
    animals = db.relationship('Animal', backref='cage', lazy='dynamic', cascade="all, delete-orphan")

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

class Animal(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(100), unique=True, nullable=True)
    cage_id = db.Column(db.Integer, db.ForeignKey('cage.id', use_alter=True), nullable=False)
    species_id = db.Column(db.Integer, db.ForeignKey('species.id', use_alter=True), nullable=False)
    sex = db.Column(db.String(10), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey('source.id', use_alter=True), nullable=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    termination_date = db.Column(db.Date, nullable=True)
    termination_reason_id = db.Column(db.Integer, db.ForeignKey('termination_reason.id', use_alter=True), nullable=True)
    events = db.relationship('AnimalEvent', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    breeding_pair = db.relationship('BreedingPair', back_populates='offspring', foreign_keys=[breeding_pair_id])
    weights = db.relationship('WeightLog', backref='animal', lazy='dynamic', cascade="all, delete-orphan")
    feedings = db.relationship('FeedLog', backref='animal', lazy='dynamic', cascade="all, delete-orphan")

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

        weights = db.session.query(cls, WeightLog).join(WeightLog) \
            .filter(
            WeightLog.date >= start_date,
            WeightLog.date <= end_date,
            #WeightLog.weight.is_not(None),
            #WeightLog.baseline == False
        ).all()

        feeds = db.session.query(cls, FeedLog).join(FeedLog) \
            .filter(
            FeedLog.date >= start_date,
            FeedLog.date <= end_date,
        ).all()

        w_animals, weights = zip(*weights)
        f_animals, feeds = zip(*feeds)
        animals = sorted(set(w_animals) | set(f_animals), key=lambda x: x.display_id)
        results = {a: [{'date': start_date + timedelta(days=i), 'weight': None, 'feeds': []} \
                       for i in range(total_days)] for a in animals}

        for weight in weights:
            ix = (weight.date - start_date).days
            if 0 <= ix < total_days:
                results[weight.animal][ix]['weight'] = weight

        for feed in feeds:
            ix = (feed.date - start_date).days
            if 0 <= ix < total_days:
                results[feed.animal][ix]['feeds'].append(feed)

        return results


class BreedingPair(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    male_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', use_alter=True), nullable=False)
    male = db.relationship('Animal', foreign_keys=[male_animal_id])
    female_animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', use_alter=True), nullable=False)
    female = db.relationship('Animal', foreign_keys=[female_animal_id])
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    litters = db.relationship('Litter', backref='breeding_pair', lazy='dynamic', cascade="all, delete-orphan")
    offspring = db.relationship('Animal', back_populates='breeding_pair', foreign_keys='Animal.breeding_pair_id')

class Litter(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    breeding_pair_id = db.Column(db.Integer, db.ForeignKey('breeding_pair.id', use_alter=True), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    pup_count = db.Column(db.Integer, nullable=False)
    wean_date = db.Column(db.Date, nullable=True)

    @property
    def age_in_days(self):
        return (date.today() - self.dob).days

class Feed(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    weight = db.Column(db.Float, nullable=False)

class WeightLog(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    date = db.Column(db.Date)
    weight = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text)
    baseline = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint('animal_id', 'date'),
    )

class FeedLog(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id'), nullable=False)
    feed_id = db.Column(db.Integer, db.ForeignKey('feed.id'), nullable=False)
    date = db.Column(db.Date)
    quantity = db.Column(db.Integer, nullable=False)  # Number of pellets
    feed_type = db.relationship('Feed')

    @property
    def total_grams(self):
        return self.amount * self.feed_type.weight

    __table_args__ = (
        UniqueConstraint('animal_id', 'feed_id', 'date'),
    )

class AnimalEvent(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', use_alter=True), nullable=False)
    procedure_id = db.Column(db.Integer, db.ForeignKey('animal_procedure.id', use_alter=True), nullable=False)
    procedure_target_id = db.Column(db.Integer, db.ForeignKey('animal_procedure_target.id', use_alter=True), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    completion_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)

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
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    reagents = db.relationship('Reagent', backref='panel', lazy='dynamic', cascade="all, delete-orphan")
    ears = db.relationship('Ear', backref='panel', lazy=True)

class Reagent(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id'), nullable=False)

class Ear(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animal.id', use_alter=True), nullable=False)
    side = db.Column(db.String(5), nullable=False)
    cryoprotection_date = db.Column(db.Date, nullable=True)
    dissection_date = db.Column(db.Date, nullable=True)
    immunolabel_date = db.Column(db.Date, nullable=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('immunolabeling_panel.id', use_alter=True), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    confocal_images = db.relationship('ConfocalImage', backref='ear', lazy=True)

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
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    confocal_images = db.relationship('ConfocalImage', backref='image_type', lazy=True)

class ConfocalImage(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    ear_id = db.Column(db.Integer, db.ForeignKey('ear.id', use_alter=True), nullable=False)
    frequency = db.Column(db.Integer, nullable=False)
    image_type_id = db.Column(db.Integer, db.ForeignKey('confocal_image_type.id', use_alter=True), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(150), nullable=True)

    @property
    def full_display(self):
        return f'{self.ear.full_display} {self.image_type.name} {self.frequency}'

class Study(VersionedModel):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    animals = db.relationship('Animal', secondary=study_animals, lazy='dynamic', backref=db.backref('studies', lazy='dynamic'))


orm.configure_mappers()