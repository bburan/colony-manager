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
