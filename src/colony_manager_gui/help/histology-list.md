---
title: The histology list
section: Histology
order: 10
summary: One row per ear, with the processing dates and the filters over them.
see_also: histology-grid, ear-detail
---

# The histology list

One row per ear, with the four dates an ear passes through and the
immunolabeling panel it was labeled with. This is the bench-work view:
what has been cryoprotected, dissected, labeled, and what is still
waiting.

Ears are created when an animal is [terminated](/help/animal-detail) with
ears extracted, or by hand from the animal page.

The species selector in the navigation bar applies to this page.

## Columns

| Column | Meaning |
|---|---|
| **Note** | hover for the cage, animal and ear notes together; click to edit the ear note |
| **ID** | animal ID and side, linked to the [ear page](/help/ear-detail) |
| **Tags** | ear tags |
| **Euthanasia** | the animal's termination date |
| **Cryoprotection**, **Dissection**, **Immunolabel** | the ear's own dates |
| **Panel** | the immunolabeling panel used |
| **Action** | image count, edit, and — only for an ear with no images — delete |

The camera button shows the ear's confocal images on hover and is filled in
blue once there is at least one. The pencil edits the dates, panel and tags
in place without leaving the list.

## Filters

| Filter | What it does |
|---|---|
| **Side** | Left / Right |
| **Sex** | the animal's sex |
| **Immunolabel** | *Labeled* means a panel has been assigned; *Pending* means none has |
| **Cryo** | whether a cryoprotection date is recorded |
| **Analysis** | where the ear's confocal images have got to — see below |
| **Ear Tag**, **Animal Tag**, **Event Tag**, **Procedure** | as on the animal list — selecting a parent includes everything nested beneath it |
| **Study** | ears whose animal is in that study |

Sort by ID, or by any of the euthanasia / cryoprotection / dissection /
immunolabel dates. Sorting by a date descending puts the most recent
first and pushes ears with no date to the end — the quickest way to see
what is next in the queue.

### The Analysis filter

| Option | Shows |
|---|---|
| **Pending** | ears with at least one image still to be worked — imaged or needing review |
| **Imaged** | ears with at least one image acquired but not yet analyzed |
| **Needs Review** | ears with at least one image flagged for a second look |
| **Done** | ears that have images, none of them outstanding |

*Pending* is the union of *Imaged* and *Needs Review* — the whole
outstanding queue in one click.

For **Done**, an image marked *Region missing* or *Poor histology* counts
as resolved: there is nothing left to analyze either way. An ear with no
images at all is neither pending nor done — nobody has started it, which
is a different thing from having finished.

> "Labeled" keys off the **panel**, not the immunolabel date: the date is
> sometimes left blank even when the work was done, but a panel is always
> chosen.
