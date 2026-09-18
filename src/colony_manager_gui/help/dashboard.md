---
title: The dashboard
section: Colony
order: 10
summary: What each panel on the landing page is counting, and over what window.
see_also: calendar, animal-detail, histology-list
---

# The dashboard

The landing page. Every panel is a shortcut to work that needs doing;
nothing on it is edited in place, and every entry links to the record it
describes.

Everything here respects the species filter in the navigation bar.

## Counters

Four cards along the top: **Active Breeding Pairs**, **Active Cages**,
**Active Animals** and **Unlabeled Ears**, each broken down by species.
Click a card to go to the list it counts.

"Active" means not terminated for animals, and "has at least one
non-terminated animal" for cages. An unlabeled ear is one with no
immunolabeling panel assigned yet.

## Weights

A grid of animals against the last two weeks and the next few days. Each
cell shows the animal's weight as a **percentage of its baseline weight**,
with the day's total feed as a small badge beside it. Cells are coloured
when the animal is off target:

| Colour | Meaning |
|---|---|
| Blue | this entry is the animal's baseline weight |
| Amber | 75–80% of baseline |
| Red | below 75% of baseline |
| Plain | 80% of baseline or above, or no baseline recorded |

Click any cell to add or edit that day's weight and feed. Empty cells show
a `+` button that does the same thing. An animal with no baseline weight
recorded shows a dash rather than a percentage — set one from the animal's
Weight & Feed panel.

## Recently Completed Events

Events completed in the last 7 days, grouped by animal, most recent first.
Expanding a row shows the files attached to each event.

## Recent Confocal Images

Confocal image files whose *file modification time on disk* falls in the
last 7 days, grouped by ear. This is the fastest way to see what came off
the microscope this week. Files that arrived but could not be matched to
an image record are listed separately at the bottom of the panel — those
need attention on the [Unmatched Data Files](/help/unmatched-data) page.

## Upcoming Litters

Every litter that has not been weaned yet, oldest first, with pup count and
age. Click through to the breeding pair to record the wean.

## Animals Without a Study

Active animals that have an ID, are not enrolled in any study, and are not
currently one half of an active breeding pair — the pool available for new
work. The line above the list counts animals that have no ID assigned at
all; those are the truly uncommitted animals.

The list is capped at 100 entries. Use the
[animal list](/help/animal-list) with the Study filter set for the full
set.

## Recently Terminated

Animals terminated in the last 7 days.

## Images pending analysis / review

Confocal images sitting in the **Imaged** state (acquired, not yet
analyzed) and the **Needs review** state, grouped by ear and image type,
with a badge per frequency. Click through to the ear to work on them.
