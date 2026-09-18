---
title: The histology grid
section: Histology
order: 20
summary: Ears against frequency, colour-coded by imaging status, with conflict flags.
see_also: histology-list, ear-detail, unmatched-data
---

# The histology grid

Ears down the side, frequencies across the top, one coloured square per
image. It answers "where are we with the imaging?" for a whole cohort at a
glance, which the row-per-ear [list](/help/histology-list) cannot.

## Tabs

One tab per confocal image type (IHC/OHC counts, synaptogram, and so on).
Switching tabs keeps every filter you have set.

The frequency columns are whatever frequencies actually exist for the ears
currently in scope, so the grid narrows as you filter.

## Filters

The same filter card as the [histology list](/help/histology-list), plus
one extra: **Conflicts** — *Conflicts only* reduces the grid to ears that
have at least one flagged square or one orphan file. That is the review
queue.

## Reading a square

The **fill colour** is the image's processing status:

| Colour | Status | Meaning |
|---|---|---|
| Cyan | Imaged | acquired, not yet analyzed |
| Green | Analyzed | analysis complete |
| Amber | Needs review | analyzed, but something needs a second look |
| Dark grey | Region missing | that region does not exist on this cochlea |
| Grey | Poor histology | the region exists but is not usable |

The **glow around a square** flags a disagreement between the status and
the files linked to it:

| Glow | Conflict |
|---|---|
| Red | the files contradict the status — a status that implies imaging happened but no file linked, or a region marked missing that nevertheless has one |
| Black | more than one file linked, where the grid expects one image per cell |
| Orange | marked analyzed, a file is linked, but no linked file reports a completed analysis |

A file whose rating has simply never been checked does not count as
missing analysis, so it raises no orange glow.

A **red hatched square** is an *orphan file*: a data file whose filename
parses to this ear, this image type and that frequency, but for which no
image row exists. Either the image record has not been created yet, or the
filename disagrees with what was recorded. Orphans at a frequency with no
column of its own are collected in a trailing **Other** column.

Hover any square for its status, file count and conflict in words.

## Working from the grid

- **Click a square** to edit that image — status, notes and linked files.
  The square updates in place.
- **The pencil beside an ear** edits the ear's dates, panel and tags.
- **The ear ID** opens the [ear page](/help/ear-detail), which is where you
  add image rows and see the files themselves.
