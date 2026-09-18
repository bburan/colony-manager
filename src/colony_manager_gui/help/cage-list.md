---
title: The cage list
section: Colony
order: 50
summary: Filtering cages by occupancy, sex composition and source.
see_also: cage-detail, animal-list
---

# The cage list

One row per cage. Cages whose animals have all been terminated are shown
greyed out but are never removed.

The species selector in the navigation bar applies to this page.

## Filters

| Filter | What it does |
|---|---|
| **Status** | *Active* (at least one living animal), *Inactive* (none), or All |
| **Sex** | *M* / *F* means every animal in the cage is that sex; *Mixed* means the cage holds both |
| **Occupancy** | *Empty*, *Single* (one living animal), *Multi* (more than one) |
| **Notes** | whether the cage has a note written on it |
| **Source** | cages holding at least one animal from that source |
| **Animal Tag** | cages holding an animal with that tag, or any tag nested beneath it |
| **Procedure** | cages holding an animal with an event of that procedure, or any beneath it |

Sort by cage ID, age, total animals or living animals, and flip direction
with the arrow button. All of it is carried in the URL, so a filtered view
can be bookmarked.

## Columns

- **Animals / Original** — every animal ever recorded in the cage.
- **Animals / Remaining** — the ones not yet terminated.
- **Age** — the age of the animals in the cage, in the unit chosen in the
  navigation bar. Cages whose animals differ in age show a range.
- **Source** — the breeding pair the animals came from, if they were bred
  here, otherwise the external source they were bought from.
- **Date of target age** — appears when a **Target Age** such as `8w` is
  entered; the date the cage reaches that age.

The pencil button at the end of each row edits the cage without leaving
the list. The badged box button in the card header creates a new cage.

## Creating a cage

The new-cage form doubles as a bulk animal creator: giving it a sex, a
date of birth and a number of animals creates that many animals inside the
new cage at once. They start without IDs — assign those later from the
[cage page](/help/cage-detail) as the animals are identified. Enter `0` to
create an empty cage.

Cage IDs must be 4 to 10 characters and unique across the whole colony.
