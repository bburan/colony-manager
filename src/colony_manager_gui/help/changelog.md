---
title: Changelog
section: Changelog
order: 10
summary: What changed in the app, newest first.
see_also: overview, navigation
---

# Changelog

Each entry below is one update to the live app, dated by the day it
landed, newest first. Only changes you would notice while using the
database are listed — a page that moved, a filter that now returns
different rows, a new field, a new kind of data file. Internal work with
no visible effect is left out.

If something on a page does not match what the rest of this help says,
check here first: the behaviour probably changed.

## 2026-09-25

**The app has its own icon.** Browser tabs, bookmarks and the bookmark
bar now show the blue DNA mark from the top left of the navigation bar
instead of a blank page symbol. A bookmark you saved earlier may keep
showing the blank one until you open the page again or re-add it.

## 2026-09-24

**Every analyzable file shows whether it has been analyzed.** Files whose
analysis the app can check — ABR, IHC/OHC counts, synaptograms — now
carry a small badge at the right of their row: *Analyzed*, *Partial*,
*Not analyzed*, *Unchecked* (not scanned yet) or *Skipped*. It replaces
the old green/orange dot, which looked too much like the review-status
dot beside it. Confocal image rows on the ear page, which showed nothing
before, have it too. Hover the badge for the detail. See [Working with
data files](/help/data-files).

**Mark extra copies so nobody analyzes them.** When there is more than
one image of the same ear and frequency, click a file's analysis badge
and choose **Skip** for the copies that don't need analysis. A skipped
file drops off [Needs Analysis](/help/unrated-data) and out of the
[Analysis Scoreboard](/help/analysis-scoreboard). Skip is different from
**Excluded**: excluded means the file is flawed, skip means it is fine
but not needed. **Analyze** is for keeping more than one copy on
purpose; every file starts as **Not set**, which is analyzed as before.
The menu's *What do these mean?* link explains the three.

**Needs Analysis is shorter.** Files marked Excluded or Missing used to
stay on [Needs Analysis](/help/unrated-data) and count as "not started"
on the scoreboard. They are now left out of both, so the completion
percentages may go up.

**The histology grid's black glow asks for a decision.** A square with
more than one file used to glow black no matter what. It now clears
once the extra copies are set to Skip or Excluded, or every copy is set
to Analyze. Skipped and excluded copies are also ignored for the orange
"marked analyzed but no analysis" glow. See the [histology
grid](/help/histology-grid).

**Poor histology and missing regions are left out of the analysis
counts.** Confocal files whose image is marked *Poor histology* or
*Region missing* no longer appear on [Needs
Analysis](/help/unrated-data) or anywhere on the [Analysis
Scoreboard](/help/analysis-scoreboard) — even if someone analyzed them —
and their badge names the image status instead of *Not analyzed*. The
scoreboard's per-analyst counts and recent activity now also leave out
skipped, excluded and missing files, matching its completion bars, so
some people's totals may drop. Change an image back to *Imaged* and its
files return.

## 2026-09-23

**Image files are easier to read.** Photos, scans and PDFs attached to an
animal or ear used to sit in a grid of small cards, with the filename and
note squeezed into a column a few characters wide. They are now one row
each: a larger thumbnail on the left, and the filename, note and review
status laid out beside it. The note is visible and editable on the row
itself rather than hidden behind a hover — image rows no longer need
expanding at all. Non-image files are unchanged. See [Working with data
files](/help/data-files).

**Uploads take a name and a note, separately.** The upload box used to
have one box per file, and whatever you typed became part of the
filename — so rewording it later left the file named after the old
wording. There are now two boxes: the **name** goes into the filename,
the **note** is kept with the file and can be changed freely. Leave the
name blank and the file is numbered for you — *image 1*, *image 2* —
carrying on past anything already there. An upload never replaces an
existing file: a name already in use gets a number added rather than
overwriting, and that now holds across different file types and
capitalisation too, so you will not end up with two rows you cannot tell
apart.

**PNG photos and PDF dissection notes are recognised.** A photo type
only ever accepted `.jpg` and `.pdf`, and dissection notes only `.jpg`.
Anything else — a `.png` screenshot of a setup or a recording, say —
uploaded and displayed fine but was invisible to the sync, so it would
not have been picked up again if it were ever re-read from the storage.
`.png` and `.jpeg` now count as photos for both, and dissection notes
accept `.pdf` as well. Dropping a `.png` straight into a photo folder
now works too, where the sync used to skip it.

**Animal photos are named in a readable order.** A photo uploaded
through the interface is now filed as *animal - date - name*, where it
used to be *date - animal - note*; a photo covering several animals
separates them with `+` instead of a space. The old order could not be
read back by the sync, so an uploaded photo was invisible to it — a
photo re-scanned from disk would have been missed. Photos uploaded
before today keep their old names until an administrator runs the
one-off rename; nothing you can see in the app changes either way.

**Events cannot be auto-created after an animal died.** The wand button
on an unassigned file, and *Auto-create events* on the
[Unmatched Data Files](/help/unmatched-data) page, now refuse a file
dated after the animal's termination date and say so, instead of
creating the event. A file dated later than the animal's death is
usually attached to the wrong animal — a re-used or mistyped ID — so it
is worth reading the filename before anything else. A file dated *on*
the termination date is fine and still works, since the last procedure
and the euthanasia happen the same day. Scheduled syncs apply the same
rule and leave such files unmatched.

**Moving a file to another event shows fewer options.** The event
dropdown on a file now lists only events on that file's own date rather
than the animal's entire history, which for an old animal was a long
scroll. A file whose date could not be read still shows everything.

## 2026-09-22

**Sign in with your OHSU account.** The sign-in page now has an *OHSU
Login* button above the email and password fields, so you no longer need
a separate Colony Manager password. Your existing password still works —
both routes reach the same account. The first time you use the button,
your OHSU identity is matched to your account by email address; if the
address on your account is not your OHSU one, ask an administrator to
correct it first, or you will be told that no account exists. If OHSU
sign-in is ever unavailable, the password form below it keeps working.

## 2026-09-21

**The navigation bar is more compact.** The "Colony Manager" wordmark and
the separate *Dashboard* item are gone — the DNA mark on the left now
links to the dashboard. *Help* and *Settings* are icon-only: the
question-mark and gear buttons on the right. The species filter and age
unit are unchanged. See [Finding your way around](/help/navigation).

## 2026-09-18

**In-app help.** Every page now has a `?` button in its header that opens
the help for that page, and the whole set is browsable at
[Help](/help/).

**The histology Analysis filter works.** *Pending*, *Needs Review* and
*Done* previously returned no ears at all, so the list and grid looked
empty rather than filtered. All four options now filter properly:
*Pending* is anything still to work on (imaged or needs review), *Done*
is an ear that has images with nothing outstanding, and an ear nobody has
imaged yet is neither. See [The histology list](/help/histology-list).

## 2026-09-17

**Editing a note no longer clears the rest of the animal.** Saving the
notes-only or assign-ID modal on an animal used to un-terminate the
animal, clear its termination date and reason, and drop all of its tags.
Those modals now touch only their own field. If an animal lost its
termination or tags this way, re-enter them from the full edit form.

## 2026-09-16

**A terminated animal's age stops at termination.** Ages used to keep
counting up from the date of birth to today, even after euthanasia. A
terminated animal now shows its age on the day it was terminated, and one
terminated with no date recorded shows `N/A` rather than a made-up
number. Age filters skip those unknown ages instead of matching them by
accident.
