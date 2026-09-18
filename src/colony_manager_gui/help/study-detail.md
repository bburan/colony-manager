---
title: The study page
section: Colony
order: 100
summary: The event coverage matrix, and files shared across animals.
see_also: study-list, animal-detail, data-files
---

# The study page

A study's cohort, plus two review panels that only make sense across a
whole cohort.

## Animals in Study

The same table as the [animal list](/help/animal-list). The last column's
button removes an animal from the study — it does nothing else to the
animal.

## Description

Name and description, editable with the pencil. The clone button makes a
new, empty study described the same way.

## Event Coverage by Procedure

This is the point of the page: one panel per **root procedure**, showing
which animals have had it and when.

Procedures are a hierarchy, and a panel is keyed on the *root* of that
hierarchy plus the procedure target. So "Noise exposure" is one panel even
if the events beneath it record several different exposure levels; the
level shows up as an italic sub-label inside the cell rather than
fragmenting the panel.

The panel header carries:

- the procedure name, linked to the animal list filtered to that procedure;
- the total number of events in the panel;
- an **"N animals incomplete"** warning when some animals in the study have
  no event in this procedure at all. Those rows are greyed and flagged.

### Reading a cell

Columns are grouped by **side** (Left / Right / no side), and within each
side there is one column per **event tag**, plus an *(untagged)* column.
A cell holds the date — or date range, with a `×N` badge when there is
more than one event — for that animal × side × tag combination. A dash
means nothing recorded.

Grouping by tag is what lets a cohort be compared when the same procedure
was done under different conditions: tag the events and each condition
gets its own column.

### The Columns menu

Studies accumulate tags, and most panels only need a few. The **Columns**
button hides tag columns and drag-reorders them. The arrangement is saved
**per study, per panel, in your browser** — it is a personal view
preference, not shared with colleagues, and tags added later are appended
at the end.

## Data Files Shared Across Animals

One row per data file that is attached to events on **two or more animals
in this study**. Multi-animal recordings are legitimate and this is how you
confirm them; a file here that should belong to one animal is a linking
mistake worth chasing on the [animal page](/help/animal-detail).

The panel is hidden entirely when no file is shared. It deliberately only
considers animals in this study — a file shared with an animal outside the
cohort is a different question, and belongs on the
[Unmatched Data Files](/help/unmatched-data) page.
