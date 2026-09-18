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
| **Analysis** | ears having a confocal image in a given processing state |
| **Ear Tag**, **Animal Tag**, **Event Tag**, **Procedure** | as on the animal list — selecting a parent includes everything nested beneath it |
| **Study** | ears whose animal is in that study |

Sort by ID, or by any of the euthanasia / cryoprotection / dissection /
immunolabel dates. Sorting by a date descending puts the most recent
first and pushes ears with no date to the end — the quickest way to see
what is next in the queue.

> "Labeled" keys off the **panel**, not the immunolabel date: the date is
> sometimes left blank even when the work was done, but a panel is always
> chosen.
