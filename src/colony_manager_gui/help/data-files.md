---
title: Working with data files
section: Data files
order: 10
summary: How files are found, matched, previewed and marked up — the concepts behind every file row in the app.
see_also: unmatched-data, unrated-data, settings-datatypes, animal-detail
---

# Working with data files

Experimental data lives on the lab's storage, not in Colony Manager. What
the app keeps is a **record** of each file: where it is, what kind of data
it is, which animal, ear, event or image it belongs to, and what has been
done with it. Nothing here moves, renames or deletes your data.

File rows look the same everywhere they appear — the animal page, the ear
page, the study page, the review lists — so this topic covers all of them.

## How a file gets here

**By sync.** Each [data type](/help/settings-datatypes) has one or more
*locations*: directories on the storage. A sync walks those directories
and, for anything new, asks that data type's parser to read the filename.
The parser returns the animal ID (or IDs), the date and, where relevant,
the side, frequency and image type. The app then finds the matching record
and links the file to it.

**By upload.** Some data types accept files through the interface. The
**Upload** button on an animal or ear page takes one or more files, a date,
and for each file a **name** and a **note**. The name is folded into the
file's name on disk; the note is commentary stored alongside the file and
kept out of its name, so you can reword it later without renaming anything.
Leave the name blank and the file is numbered for you — *image 1*,
*image 2*, and so on, continuing past anything already there rather than
replacing it. Each file is renamed according to the same convention the
parser expects, written into the chosen location, and linked — so an
uploaded file and a synced file are indistinguishable afterwards.

Syncs are run by an administrator from
[Settings → Data Types](/help/settings-datatypes), or on a schedule.

## Reading a file row

Files that are images or PDFs render as thumbnails; everything else is a
list. Either way a row carries:

**A status dot**, the leftmost icon:

| Icon | Status | Meaning |
|---|---|---|
| Hollow circle | Unreviewed | nobody has looked at it yet |
| Check | Reviewed | looked at, keep |
| Cross | Excluded | looked at, do not use |
| Warning | Missing | the record exists but the file is gone from disk |

Change the status with the check / ban / undo buttons that appear when the
row is expanded.

**A rating dot** on data types that report analysis status: a green check
for analyzed, an orange exclamation for not. Hover it for the detail —
for a partial analysis this is where it says what is missing.

**A warning triangle** when the filename names an animal that the app could
not link to anything. Hover it for the IDs in question. These files are
what the [Unmatched Data Files](/help/unmatched-data) page collects.

**A note field**, saved as you type.

**Preview buttons** on the right — see below.

Expanding a row (click the filename) shows the note field, the status
buttons, and — for files attached to an event — a dropdown to move the file
to a different event of the same animal, or to detach it entirely.

## Preview buttons

What appears depends on the data type; each is defined by that type's
parser and opens without leaving the page:

| Button | What it does |
|---|---|
| Chart | an interactive plot |
| PDF | opens a pre-generated PDF in a new tab |
| List | a table of values — settings, thresholds, computed results |
| Image | a rendered image |
| Video | an embedded player |

A preview that fails — because the upstream processing step has not been
run, or a file is missing — shows an error in the popup rather than
breaking the page. That is normal for optional outputs.

For what each button means for a specific kind of experiment, see the
data-type topics in the [help index](/help/) — those are supplied by the
deployment's data plugin and describe the actual experiments.

## When something does not line up

Three pages exist for exactly this, all under the **Data** menu:

- [Unmatched Data Files](/help/unmatched-data) — files that matched nothing,
  or matched only part of what their name claims, or have vanished from
  disk.
- [Needs Analysis](/help/unrated-data) — files that are complete but not
  yet analyzed.
- [Analysis Scoreboard](/help/analysis-scoreboard) — how much is analyzed,
  by whom, and how recently.
