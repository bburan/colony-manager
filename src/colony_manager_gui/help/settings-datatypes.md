---
title: Settings — data types
section: Administration
order: 20
summary: Configuring parsers and locations, and running sync, rematch and force-rematch.
see_also: data-files, unmatched-data, settings-general
---

# Settings — data types

**Administrators only.** This is where the app is told what kinds of
experimental data exist, where they live on disk, and how to read their
filenames.

## What a data type is

A **data type** ties four things together:

1. a **name** and description, which is what appears on every file badge;
2. a **target type** — what the file attaches to: an animal event, a
   confocal image, an animal, or an ear. This is fixed when the data type
   is created;
3. a **description class**, chosen from a dropdown: the parser that reads a
   filename, computes the file's identity hash, and supplies the preview
   buttons. These come from the deployment's data plugin, not from Colony
   Manager itself;
4. one or more **locations** — base directories on the storage. A sync
   walks each one.

Animal-event data types have three more settings:

- **Default procedure** and **Default procedure target** — used when an
  event has to be created for a file that has none.
- **Auto-create event for unmatched files?** — when set, a sync creates
  that event automatically rather than leaving the file for the
  [Unmatched](/help/unmatched-data) page. The list shows an
  **Auto-create** badge for data types with it on. A file dated after its
  animal's termination date is never auto-created; the sync logs it and
  leaves the file unmatched for a person to look at.

## Not Set Up

Parsers that the plugin offers but which no data type uses yet. Nothing
they describe is being synced. This card exists because such a parser is
otherwise invisible — the only way to notice one was to open the Add
dropdown and read it against the existing list. **Set up** starts a new
data type pre-filled with that parser; you still have to give it a name,
a target type and a location.

A data type whose parser has *left* the plugin is flagged the other way
round: its dropdown entry reads `(unregistered)`.

## The four actions on a data type

| Action | What it does |
|---|---|
| **Sync now** (magnifier) | walk the locations and import files not already recorded. Existing rows are left alone. |
| **Re-run matching** (arrows) | re-parse and re-match only the files that never resolved a target. Safe to run any time; the fix after adding a missing animal or ear. |
| **Force rematch** (circular arrow) | clear **every** file's target links and candidates in this data type and resolve them again from scratch. Use after changing a parser's rules — it undoes manual link corrections too. |
| **Delete** (trash) | remove the data type and its file records. Files on disk are untouched. |

**Sync All Now** at the top runs a sync across every data type that has
both a parser and a location.

## Sync Jobs

All four run in the background; this panel is where you watch them. It
refreshes itself every five seconds.

Each row shows status (pending → running → success or failed), when it was
queued, what kind of job it was, which data type, a one-line result, and
how long it took. A successful run summarises as
*added / matched / moved / missing / unmatched / auto-created*, or "no
changes".

Click any row for the full counts — and, for a failure, the recorded
error. That detail is the first place to look when a sync does not do what
you expected; there is no need to go to the server logs.

> A sync that reports success having added nothing usually means the
> parser rejected every file it saw: most often the parser expects folders
> and was pointed at files, or the filenames do not follow the convention
> it reads.
