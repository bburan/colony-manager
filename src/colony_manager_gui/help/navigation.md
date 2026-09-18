---
title: Finding your way around
section: Getting started
order: 20
summary: The navigation bar, jump-to search, and the two session preferences.
see_also: overview
---

# Finding your way around

Everything in the navigation bar is available from every page.

## Jump to

The search box on the left of the navigation bar searches animals, cages,
studies and ears at once and shows matches as you type. Press `/` from
anywhere to focus it.

A single word is matched as a substring of an ID or name. Add a second
word to say *what kind of thing* you mean, which matters when a cage and
an animal share an ID:

| You type | You get |
|---|---|
| `G020-1` | every animal, cage, study and ear matching `G020-1` |
| `G020-1 cage` | only the cage |
| `G020-1 ear` | both ears of that animal |
| `G020-1 left` | the left ear — `left` and `right` imply "ear" |

Hint words are stripped before matching, so a cage genuinely named
`Cage9` is still found by typing just `Cage9`.

## Menus

- **Dashboard** — today's picture of the colony.
- **Calendar** — scheduled and completed events on a month grid.
- **Breeding**, **Cages**, **Animals**, **Studies** — the colony lists.
- **Histology** — *List* (one row per ear) and *Grid* (ears × frequency).
- **Data** — *Unmatched*, *Needs Analysis* and *Analysis Scoreboard*: the
  three views over data files that need attention.
- **Settings** — administrators only. General vocabulary lists, and Data
  Types.
- **Help** — these pages.

## Species

The paw menu filters most of the app to one species, or to **All**. It
affects the dashboard counts, the animal / cage / histology lists and the
dashboard weight table. It does *not* filter the data-file pages, which
are organised by data type rather than by animal.

## Age unit

The clock menu switches every displayed age between days, weeks and
months. The animal and cage lists have their own age controls that
override it for that page only.

## Your account

The person menu holds **Change Password**, **Logout**, and — for
administrators — **User Management**.

> A coloured navigation bar with a **DEBUG** badge means you are looking at
> a development instance, not the live one.
