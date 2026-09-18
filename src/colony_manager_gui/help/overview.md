---
title: How Colony Manager is organised
section: Getting started
order: 10
summary: The records the app keeps, and which page owns each one.
see_also: navigation, animal-detail, data-files
---

# How Colony Manager is organised

Colony Manager tracks a breeding colony and the experimental data
collected from it. Almost everything in the app is one of seven kinds of
record, and each one has a list page and a detail page.

## The records

**Cage** — a physical cage. Every animal lives in exactly one. A cage has
a species, a source, an ID and free-text notes. Cages are never deleted;
a cage whose animals have all been terminated simply stops counting as
active.

**Animal** — one animal, always inside a cage. An animal is created with a
sex and a date of birth, and *may* not have an ID yet: animals born into a
cage exist as unnamed placeholders until someone assigns a custom ID. The
animal list only shows animals that have an ID.

**Event** — something done to an animal on a date: a procedure, optionally
against a target (a body part or preparation) and a side. An event has a
*scheduled* date and, once it happens, a *completion* date. The gap
between those two is what drives "due" and "overdue" everywhere in the
app.

**Ear** — the left or right ear of an animal, as a histology specimen. Ears
are created from the animal page and carry their own dates
(cryoprotection, dissection, immunolabeling), an immunolabeling panel,
tags and notes.

**Confocal image** — one imaged region of an ear, identified by image type
(for example IHC/OHC counts or synaptogram) and frequency. Its status
tracks it from imaged through analyzed.

**Study** — a named group of animals. Studies do not change anything about
an animal; they are a way to slice the colony and to compare what has been
done across a cohort.

**Breeding pair** — a male and a female, with the litters they produce.
Weaning a litter turns pups into real animals in new cages.

**Data file** — a file (or folder) on the lab's storage that the app has
discovered and linked to an event, an animal, an ear or a confocal image.
See [Working with data files](/help/data-files).

## How they fit together

```
Cage ──< Animal ──< Event ──< Data file
             │        │
             │        └──< tags
             ├──< Ear ──< Confocal image ──< Data file
             └──< Study membership
```

A read of that diagram: a cage holds many animals, an animal has many
events and up to two ears, an ear has many confocal images, and data files
hang off whichever of those a given kind of data belongs to.

## Two things that colour the whole app

**The species filter** in the navigation bar scopes most list pages and the
dashboard to one species. If a page looks emptier than expected, check it.

**The age unit** (day / week / month) in the navigation bar controls how
every age is displayed. It is a display preference only — nothing is
stored differently.

Both are remembered per browser session. See
[Finding your way around](/help/navigation).
