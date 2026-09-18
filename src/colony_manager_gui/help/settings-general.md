---
title: Settings — general
section: Administration
order: 10
summary: The vocabulary lists the rest of the app chooses from, and dosage protocols.
see_also: settings-datatypes, users, animal-detail
---

# Settings — general

**Administrators only.** Every dropdown elsewhere in the app is filled
from one of the lists here. The sidebar jumps between sections.

## The vocabulary lists

| List | Used for |
|---|---|
| **Species** | cages, animals, and the navigation-bar species filter |
| **Source** | where an animal came from |
| **Confocal image type** | the tabs on the [histology grid](/help/histology-grid) and the grouping on the ear page |
| **Termination reason** | the termination dialog |
| **Immunolabeling panel** | the panel assigned to an ear |
| **Feed** | the feed types on a daily log, each with a unit weight |
| **Animal procedure** | what an event records |
| **Animal procedure target** | what a procedure was done to |
| **Animal tag**, **Animal event tag**, **Ear tag** | the tag vocabularies |

### Nested lists

Procedures and all three tag lists are **hierarchies** — each entry can
have a parent. This is what makes the filters elsewhere work the way they
do: filtering the animal list on a parent procedure includes every
procedure nested beneath it, so "Noise exposure" finds animals exposed at
any level recorded under it.

Build the hierarchy to match how you want to *query* the colony, not just
how you describe it. A flat list of twenty exposure levels is much harder
to work with than one parent with twenty children.

### Procedure targets and sides

A procedure target can be marked **Requires side?**. When it is, the event
form makes the side selector mandatory — you cannot record an event against
that target without saying Left or Right. Use it for anything that exists
twice per animal.

## Dosage protocols

A protocol is a named recipe used by the dosage calculator on the
[animal page](/help/animal-detail). It carries:

- the **procedure** and **target** to record the resulting event against;
- one or more **drugs**, each with a dose in mg/kg and a stock
  concentration in mg/mL;
- notes.

The calculator turns a weight in grams into a volume per drug, and logging
a dose writes a completed event whose note freezes the concentrations that
were on file at that moment. **Revising a protocol therefore does not
rewrite past doses** — which is the point. Change concentrations freely as
stock changes.

## Renaming and deleting

Renaming an entry updates it everywhere it is used; nothing is copied.
Deleting one that is referenced anywhere is refused with *"Cannot delete
… (referenced elsewhere)"* — retire it by renaming rather than by trying
to remove it.
