---
title: The animal page
section: Colony
order: 40
summary: Events, files, weight and feed, termination, and the dosage calculator.
see_also: animal-list, ear-detail, data-files, study-detail
---

# The animal page

Everything recorded about one animal. The left column holds the animal's
own attributes; the right column holds the three things that accumulate
over its life — files, events, and weight/feed entries.

## Information

Cage, species, sex, date of birth, age, source and tags. The pencil button
edits all of them. Once the animal is terminated, the termination reason
and date appear here too.

The **archive-box button** terminates the animal. The termination dialog
asks for a date, a reason, and which **ears were extracted** — choosing
Left, Right or Both creates the corresponding [ear
records](/help/ear-detail) immediately, and any confocal image files
already on disk that name those ears are linked to them on the spot. An
animal can only be terminated once.

Terminating an animal does not delete anything. Its events, files and
study memberships all stay.

## Ears

Shown once the animal has ears, or once it is terminated. Each ear links
to its own page. This is also where ears are added if they were not
created at termination.

## Notes and Studies

Free text, and the list of studies the animal is enrolled in. The
clipboard button adds it to another study; the minus button on a row
removes it. Removing an animal from a study removes only the membership.

## Files

Data files attached to the animal itself — as opposed to a specific
event, which live in the Events panel below. Images and PDFs render as
thumbnails; everything else is a list. The **Upload** button adds a file
by hand. See [Working with data files](/help/data-files) for what the
status icons and the buttons on each row mean.

## Events

The animal's history, grouped by date. The arrow button at the top
flips between newest-first and oldest-first, and that choice is remembered
for every animal page you visit afterwards.

**Add Event** records a procedure. The form asks for:

- a **procedure**, and optionally a **target** — some targets require a
  side, in which case the side selector becomes mandatory;
- a **side**: choosing *Both* creates two events, one per side, rather
  than one ambiguous event;
- **Schedule** or **Complete**: scheduling sets only the planned date,
  completing sets the planned and the completion date to the same day.
  An animal with a scheduled event whose date has passed counts as
  overdue in the [animal list](/help/animal-list) and on the dashboard.

Files that the sync has identified as belonging to this animal but that
are not yet attached to any of its events are listed under **unassigned
files** at the bottom of the panel. Each has a dropdown to attach it to an
event, and — where the data type declares a default procedure — a wand
button that creates the right event from the file's own date.

The wand refuses if the file is dated **after** the animal's termination
date, and says so rather than creating the event: nothing happens to an
animal after it is euthanized, so a file dated later is much more likely
attached to the wrong animal — a recycled or mistyped ID — than real. A
file dated *on* the termination date is fine, since the terminal
procedure and the euthanasia share a day.

### Calculate Dose

Opens the dosage calculator. Pick a [dosage
protocol](/help/settings-general) and enter the animal's weight in grams;
the table recomputes per drug as you type, showing mg and mL per drug and
the total injection volume.

**Log dose** writes the result as a completed event, using the protocol's
procedure and target, with the date *and time* of injection. The note it
writes freezes the stock concentrations used at that moment, so revising
the protocol later does not rewrite history.

## Weight & Feed

One row per date, with weight in grams, weight as a percentage of
baseline, total feed, and notes. Rows are coloured amber below 80% of
baseline and red below 75%.

The badges at the top show the animal's **baseline weight** and its 80%
and 75% marks. Baseline is not typed in directly: tick **Baseline Weight?**
on a weight entry, and the baseline becomes the average of the most recent
unbroken run of entries marked that way. Marking three consecutive days as
baseline therefore averages those three; marking a single later day
replaces the earlier run entirely.

**Add Entry** records one day's weight and the amount of each configured
feed given. The same entries appear in the dashboard's weight grid, where
they can be added and edited without leaving the dashboard.
