---
title: Accounts and user management
section: Administration
order: 30
summary: Registration, approval, the administrator flag, and passwords.
see_also: settings-general, analysis-scoreboard
---

# Accounts and user management

Every page in Colony Manager requires a login; there is no anonymous
access. Accounts are identified by **email address**, not a username.

## Getting an account

Registration is open from the login page: the **create account** tab takes
a first name, last name, email and password.

A new account is created **inactive** and cannot log in until an
administrator approves it — the message after registering says as much.
The single exception is the very first account on a fresh installation,
which is activated and made an administrator automatically so there is
somebody to do the approving.

## Passwords

At least 8 characters, with an uppercase letter, a lowercase letter, a
digit and a punctuation character. Users change their own password from
**Change Password** in the person menu; it asks for the current password
and refuses a new one identical to it.

There is no password-reset flow in the app. Someone who is locked out needs
an administrator to intervene directly.

## User management

**Administrators only**, from the person menu. The table lists every
account with its name, email, and whether it is **Active** and an
**Admin**. The pencil on a row edits the first name, last name, email and
the active flag.

Two things the page deliberately does not do:

- **The admin flag is shown but not editable here.** Granting or revoking
  administrator rights is a database operation, not a UI one.
- **The first account cannot be edited at all**, so the bootstrap
  administrator cannot be locked out by accident.

## What being an administrator gets you

Access to **Settings** — the
[vocabulary lists](/help/settings-general) and
[data types](/help/settings-datatypes) — and to this page. Everything else
is available to every logged-in user; there are no finer-grained
permissions.

## Deactivating an account

Untick **Active**. Accounts are deactivated rather than deleted, which
keeps any record that refers to them intact. Deactivation takes effect on
that user's **next request**, not at their next login — an open session
ends as soon as they click anything.

> Analysis credit on the [scoreboard](/help/analysis-scoreboard) comes
> from the analysis files themselves, not from Colony Manager accounts, so
> the two sets of names need not match.
