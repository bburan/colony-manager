---
title: Unmatched data files
section: Data files
order: 20
summary: Files that matched nothing, matched only partly, or vanished from disk.
see_also: data-files, settings-datatypes, animal-detail
---

# Unmatched data files

**Data → Unmatched.** This page is not a file browser — every row on it is
a *problem*. A file appears here for one of two reasons, and can have both
at once.

## The two issues

**Unresolved target.** Either the file linked to nothing at all, or it
names something in its filename that the app could not find. The usual
causes:

- the animal ID in the filename does not exist in the database — a typo,
  or an animal that was never entered;
- the animal exists but the ear does not, because the animal was
  terminated without ears extracted;
- a confocal image file names a frequency or image type for which no
  image row has been created;
- an event file has no event to attach to yet.

**Missing.** The `Data` record exists but the file is no longer at its
recorded path — moved, renamed, or deleted on the storage.

The **Issue** filter splits these, and splits *missing* three ways:

| Option | Shows |
|---|---|
| All issues | anything with either problem |
| Unresolved target | files that did not fully link |
| Missing (all) | every file gone from disk |
| Missing (linked) | gone from disk, but everything it named *did* link — usually a genuine move or deletion |
| Missing (unlinked) | gone from disk *and* unlinked — usually a file that was never right in the first place |

Filter further by **target type** (animal event, confocal image, animal,
ear), by **data type**, and by a substring of the filename or path. Sort by
date, filename or data type.

## Reading a row

- **Data type** and **Target** — what kind of data it is and what kind of
  record it should attach to.
- **Location** — the path relative to the data type's location. Hover for
  the full path.
- **Unlinked objects** — one pill per animal or ear the filename names but
  did not link to:
  - a **dark pill** links to a record that exists — click through and
    attach the file there;
  - a **split pill** (dark animal, light side) means the animal exists but
    that ear does not — clicking lands on the animal page's Ears card,
    where you create it;
  - a **plain light pill** is a name with no matching record at all.

## Fixing things

**Auto-create events** takes the ticked event files and, for each one,
creates (or reuses) an animal event on the file's first candidate animal,
using the file's own date and the data type's default procedure. Sibling
files from the same run are linked to the same event. Files are skipped —
and counted in the message — when they are not event files, have no
candidate animal, or the data type has no default procedure, no parsed
date, or needs a side the filename does not give.

A file is also skipped when it is dated after its candidate animal's
termination date. That one usually means the file belongs to a different
animal, so it is worth reading the name before doing anything else.

**Delete selected** appears only under the *Missing* filters. It removes
the database records, not files — and there are no files left to remove.
Deleting records for files that are still on disk is almost never right,
which is why the button is hidden otherwise.

For anything else the fix is usually outside this page: correct the name
on disk and re-run the sync, create the missing ear or image record, or
add the animal.
