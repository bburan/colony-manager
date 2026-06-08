"""Histology-pipeline models: Ear, EarTag, ConfocalImage, ConfocalImageType,
ImmunolabelingPanel."""
from sqlalchemy import (
    Boolean, Column, Date, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import backref, relationship

from .base import NestedMixin, VersionedModel, ear_tags


class ImmunolabelingPanel(VersionedModel):
    id          = Column(Integer, primary_key=True)
    name        = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    ears        = relationship('Ear', backref='panel', lazy=True)


class EarTag(VersionedModel, NestedMixin):
    id        = Column(Integer, primary_key=True)
    name      = Column(String(150), nullable=False)
    parent_id = Column(Integer, ForeignKey('ear_tag.id'), nullable=True)
    subtags   = relationship('EarTag', backref=backref('parent', remote_side=[id]))
    __table_args__ = (UniqueConstraint('name', 'parent_id'),)


class ConfocalImageType(VersionedModel):
    id             = Column(Integer, primary_key=True)
    name           = Column(String(100), unique=True, nullable=False)
    confocal_images = relationship('ConfocalImage', backref='image_type', lazy=True)


class Ear(VersionedModel):
    id                  = Column(Integer, primary_key=True)
    animal_id           = Column(Integer, ForeignKey('animal.id',               use_alter=True), nullable=False)
    side                = Column(String(5), nullable=False)
    cryoprotection_date = Column(Date, nullable=True)
    dissection_date     = Column(Date, nullable=True)
    immunolabel_date    = Column(Date, nullable=True)
    panel_id            = Column(Integer, ForeignKey('immunolabeling_panel.id', use_alter=True), nullable=True)
    notes               = Column(Text, nullable=True)
    confocal_images     = relationship('ConfocalImage', backref='ear', lazy=True)
    tags                = relationship(
        'EarTag', secondary=ear_tags, backref='ears', order_by='EarTag.name',
    )

    @property
    def full_display(self):
        return f'{self.animal.custom_id} {self.side}'

    @property
    def events(self):
        """AnimalEvents tagged with this ear's side."""
        return [e for e in self.animal.events if e.side == self.side]

    @property
    def events_by_date(self):
        groups = {}
        for e in self.events:
            groups.setdefault(e.date, []).append(e)
        return {
            d: sorted(groups[d], key=lambda x: x.procedure.name)
            for d in sorted(groups.keys())
        }

    def __eq__(self, other):
        if not isinstance(other, Ear):
            return NotImplemented
        return self.id == other.id

    def __lt__(self, other):
        if not isinstance(other, Ear):
            return NotImplemented
        return (self.animal.custom_id, self.side) < (other.animal.custom_id, other.side)


class ConfocalImage(VersionedModel):
    id            = Column(Integer, primary_key=True)
    ear_id        = Column(Integer, ForeignKey('ear.id',               use_alter=True), nullable=False)
    frequency     = Column(Float, nullable=False)
    image_type_id = Column(Integer, ForeignKey('confocal_image_type.id', use_alter=True), nullable=False)
    notes         = Column(Text, nullable=True)
    status        = Column(String(150), nullable=True)

    @property
    def full_display(self):
        return f'{self.ear.full_display} {self.image_type.name} {self.frequency}'
