---
title: The analysis scoreboard
section: Data files
order: 40
summary: Completion per data type, who has been analyzing, and what changed recently.
see_also: unrated-data, data-files
---

# The analysis scoreboard

**Data → Analysis Scoreboard.** Where [Needs
Analysis](/help/unrated-data) is the work queue, this is the progress
report: how much of each kind of data is analyzed, who has been doing it,
and what has moved lately.

It covers the same data types as Needs Analysis — those whose files can
report their own analysis status.

## The two filters

**Data type** restricts the whole page to one type.

**Activity window** (7 / 30 / 90 days, or all time) applies to the
*analyst* and *recent* panels only. **Completion is always all-time**, so
narrowing the window never makes the colony look less finished than it is.

## Completion

One card per data type, with a bar split three ways:

| Colour | Meaning |
|---|---|
| Green | analyzed |
| Amber | partial — started, not finished |
| Grey | not started |

The percentage in the badge counts only fully analyzed files. A data type
with no files yet still gets a card, at 0%, so nothing silently drops off
the report.

## By analyst

One row per person, ordered by volume: how many analyses they are credited
with in the window, a breakdown per data type, and when they were last
active.

Credit comes from the analysis files themselves, not from Colony Manager
logins — an analysis records who saved it. **Older files predate that
record** and are counted in the completion bars but attributed to nobody,
so this panel undercounts historical work. It is a picture of recent
activity, not a career total.

## Recent analyses

The 25 most recently analyzed files in the window, newest first, each with
its data type, its animal or ear, and who did it. Files whose analysis
carries no timestamp are not listed — there is nowhere to put them on a
timeline.

## Rescan

**Rescan** re-reads analysis status for every ratable data type — or just
the filtered one — and runs in the background. The numbers here are only
as fresh as the last scan, so rescan before quoting them.
