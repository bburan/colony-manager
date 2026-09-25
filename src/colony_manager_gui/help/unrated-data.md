---
title: Needs Analysis
section: Data files
order: 30
summary: Files whose data type can report analysis status, and which are not finished.
see_also: analysis-scoreboard, data-files
---

# Needs Analysis

**Data → Needs Analysis.** The work queue: files that *can* report whether
they have been analyzed, and that are not finished.

Only some kinds of data can answer that question — ABR waveform picks, IHC
and OHC counts, synaptograms. Data types that cannot are absent from this
page entirely, and from its data-type dropdown.

Some files are left off even though their type can report status: files
marked **Excluded** or **Missing**, replicates marked **Skip** (see
[Working with data files](/help/data-files)), and confocal files whose
image is marked **Poor histology** or **Region missing** — there is
nothing usable to analyze. If a file you expected is not here, check
those first.

## Unrated vs partial

The **State** filter distinguishes two ways of being unfinished:

- **Unrated** — analysis has not started, or has never been checked.
- **Partial** — analysis started but is incomplete. A partial file says so
  in its note, usually naming what is missing.
- **Both** is the default.

## Filters

- **Data type** — one ratable type at a time.
- **Search** — substring of the filename or path.
- **Note contains** — whitespace-separated terms, all of which must appear
  in the note, in any order. `Partial OHC1` matches
  `Partial — no spiral for OHC1, OHC2, OHC3`. This is the way to pull out
  one specific kind of incompleteness across the whole colony.

Sort by date, filename or data type.

## Columns

**Targets** — the animals, ears or images the file belongs to, linked.
`unmatched` here means the file has no target at all; that is an
[unmatched-file](/help/unmatched-data) problem, not an analysis one.

**Raters** — for schemes with named raters, who has scored it. A file
needing two independent raters shows one badge until the second is done.

**Note** — what the analysis reports about itself. This is where "partial"
says what is missing.

## Re-checking

Analysis status is cached, and refreshed by a background job. Two ways to
refresh it by hand:

- **the circular arrow on a row** re-reads that one file's analysis
  straight away and updates the row in place. Use this after finishing an
  analysis to confirm the app sees it.
- **Re-scan now** in the header queues a scan of every ratable data type,
  or just the one you have filtered to. This walks a lot of files, so it
  runs in the background; watch it finish on
  [Settings → Data Types](/help/settings-datatypes).

A file that disappears from this page after a re-check is done.
