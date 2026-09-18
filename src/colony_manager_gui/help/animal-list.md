---
title: The animal list
section: Colony
order: 30
summary: Filtering and sorting animals, the target-age column, bulk study assignment.
see_also: animal-detail, cage-list, study-detail
---

# The animal list

One row per animal that has an ID. Animals created as placeholders inside
a cage (no ID assigned yet) do not appear here — find them on the
[cage page](/help/cage-detail) and give them an ID from there.

The species selector in the navigation bar applies to this page.

## Filters

All filters combine with AND, and every one of them is carried in the page
URL, so a filtered list can be bookmarked or pasted to a colleague. The
circular arrow at the top right clears everything.

| Filter | What it does |
|---|---|
| **Status** | Active (default), Terminated, or All |
| **Sex** | M / F |
| **Events** | *No Events*, *Has Event*, *Due/Overdue* (scheduled on or before today, not yet completed), *Overdue* (scheduled strictly before today, not yet completed) |
| **Procedure** | animals with at least one event of that procedure — *or any procedure nested beneath it* |
| **Animal Tag** | animals carrying that tag, or any tag nested beneath it |
| **Event Tag** | animals with an event carrying that tag, or any beneath it |
| **Study** | animals enrolled in that study |
| **Search ID** | substring match on the animal ID |

Procedures and tags are hierarchies. Filtering on a parent includes
everything under it, so "Noise exposure" finds animals exposed at any
level recorded beneath it.

## Sorting

Sort by **ID**, **Age** or **Last Event**, with the arrow button flipping
the direction. Sorting by age ascending puts the youngest first. Sorting
by last event uses each animal's most recent *completed* event; animals
with no completed events sort to the end when descending.

## Target age

Type an age such as `8w`, `21d` or `3m` into **Target Age** and a *Date of
target age* column appears, showing the calendar date on which each animal
reaches it. Dates in the past are still shown — this is the tool for
planning "when is this cohort ready", not a filter.

## Reading a row

- **Note** — hover for the cage note and the animal note together; click to
  edit the animal's note.
- **Animal ID** — links to the animal. An animal with no ID shows a tag
  button that assigns one.
- **Events** — the event count. The button's colour is the alarm: grey for
  events recorded, amber for something due, red for something overdue,
  outline for no events at all. Hover to see the events; the popover has
  its own "add event" button.
- **Studies** — the enrolment count; hover to list them, click to add the
  animal to another study.
- The last column holds the **terminate** action.

Terminated animals are shown greyed out.

## Assigning several animals to a study

Tick the animals you want (or the header checkbox to take the whole
filtered page), choose a study from **Assign to study** at the top of the
table, and press **Apply**. Animals already in that study are skipped
rather than duplicated.
