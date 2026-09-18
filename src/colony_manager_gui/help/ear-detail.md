---
title: The ear page
section: Histology
order: 30
summary: Processing dates, confocal images, and the files attached to one ear.
see_also: histology-list, histology-grid, animal-detail, data-files
---

# The ear page

Everything about one ear of one animal: its processing history, the
confocal images taken from it, and the files those produced.

## The three cards

**Notes** — free text about this ear.

**Ear** — cryoprotection, dissection and immunolabel dates, the
immunolabeling panel, and ear tags. The pencil edits all of them.

**Animal** — a read-only summary of the animal, linked to its
[animal page](/help/animal-detail).

## Events

Shown when the ear has events — that is, animal events recorded against
this side. Grouped by date, same as on the animal page.

## Files

Data files attached to the ear itself, rather than to one of its images.
Dissection photographs and notes usually live here. The **Upload** button
adds one by hand; see [Working with data files](/help/data-files).

## Unmatched Images

Appears only when there is something to show: files whose filename names
*this* ear but which did not link to any image row. Almost always the
frequency or the image type in the filename does not correspond to an
image that has been created yet.

Two ways out: create the missing image row below, which links the file
automatically, or correct the file's name on disk and re-run the sync.

## Images

One row per confocal image, grouped by image type and sorted by frequency,
with:

- the **frequency** in kHz;
- the **status** — Imaged, Analyzed, Needs review, Region missing or Poor
  histology — which is what the [grid](/help/histology-grid) colours;
- the **files** linked to it, with their preview buttons;
- **notes**;
- edit and delete actions.

The camera button in the header adds images. Creating an image row also
sweeps the ear's unmatched files: any whose parsed frequency and image
type match the new row are linked to it immediately, and the Unmatched
Images card shrinks accordingly.

> An ear can only be deleted while it has no images — from the
> [histology list](/help/histology-list). Delete the images first if an
> ear was created in error.
