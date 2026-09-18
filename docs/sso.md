# Single sign-on (OIDC)

Colony Manager can authenticate users against an institutional OpenID
Connect provider — at OHSU, the university's OAuth/OIDC client — *in
addition to* the local password form. The two are additive, not
exclusive: one account row can carry both a `password_hash` and an OIDC
identity, and either one signs you into the same account.

SSO is entirely optional. With no `OIDC_CLIENT_ID` in the environment
the app behaves exactly as it did before: no button, no extra
dependencies exercised, no code path taken.

---

## What you need from the identity provider

Registering the application with central IT is the first step, and the
conversation goes both ways. Here is what you have to **give** them and
what you need to **get back**.

### Give them

| Item | Value |
| --- | --- |
| Application name | Colony Manager |
| Application type | Confidential web application (server-side, holds a client secret) |
| Grant type | Authorization code (with PKCE) |
| Redirect / callback URI | `https://<your-host>/auth/sso/callback` |
| Post-logout redirect URI | `https://<your-host>/auth/login` (only if you want RP-initiated logout) |
| Scopes requested | `openid`, `email`, `profile` |

The redirect URI must match **exactly**, character for character,
including scheme, host, port and path — providers reject anything else.
Register one per environment you run (production, staging, a laptop on
`https://localhost:5000` if IT will allow it).

### Get back

| Item | Used as | Required |
| --- | --- | --- |
| Client ID | `OIDC_CLIENT_ID` | yes |
| Client secret | `OIDC_CLIENT_SECRET` | yes |
| Discovery document URL (`…/.well-known/openid-configuration`) | `OIDC_DISCOVERY_URL` | yes¹ |
| Issuer URL | `OIDC_ISSUER` | alternative to the above¹ |
| Which claim carries the user's email | — | yes, see below |
| Whether `email_verified` is emitted | `OIDC_REQUIRE_VERIFIED_EMAIL` | no |
| Whether the client is restricted to a user group | — | worth asking |

¹ Set either one. Given `OIDC_ISSUER`, the discovery URL is derived by
appending `/.well-known/openid-configuration`. Everything else — the
authorization, token, userinfo, JWKS and end-session endpoints — is read
out of that document at runtime, so you never hard-code an endpoint and
IdP-side endpoint changes need no redeploy.

### The claims question

Account matching is by **email address**, so it matters which claim the
provider puts the address in. Most emit `email`; some institutional
Entra ID / ADFS deployments put it in `preferred_username` or `upn`
instead, and some emit `preferred_username` as a bare username with no
domain at all. The app reads `email`, then `preferred_username`, then
`upn`, taking the first that looks like an address.

If your provider emits none of those in a usable form, ask IT to add the
`email` claim to the client's token configuration — that is normally a
one-line change on their side and much better than guessing at a
username-to-address mapping here.

Name claims (`given_name`, `family_name`, falling back to `name`) are
used only to fill in a newly provisioned account and are never required.

---

## How an account gets matched

Two tiers, in order (`services/sso.py`):

1. **By OIDC identity** — the `(issuer, subject)` pair, stored on the
   user row as `oidc_issuer` / `oidc_subject`. `sub` is the only claim
   an IdP promises never to reassign, so once an account is linked this
   is the only lookup that runs. Someone who changes their name or email
   at the institution keeps their account and their history.

2. **By email address**, once, to *establish* that link. This is the
   bootstrap path for every account that predates SSO. It is the risky
   tier — institutions do recycle addresses — so it is gated on the
   `email_verified` claim and on `OIDC_ALLOWED_DOMAINS` before the email
   is trusted. The moment it succeeds, the subject is written to the row
   and tier 2 never runs for that account again.

An account already linked to a *different* subject is never silently
re-linked; that sign-in is refused and the user is told to contact an
admin. That combination means either the provider reissued subjects or
somebody else now holds the address, and neither should be papered over.

A user who has never signed in through SSO is **not** auto-created
unless `OIDC_AUTO_PROVISION` is on. The default matches the existing
signup flow's posture: accounts exist because an admin approved them.

---

## Environment variables

```sh
# --- required to enable SSO ---
export OIDC_CLIENT_ID=<from IT>
export OIDC_CLIENT_SECRET=<from IT>
export OIDC_DISCOVERY_URL=https://login.example.edu/.well-known/openid-configuration
#   ...or, equivalently:
# export OIDC_ISSUER=https://login.example.edu

# --- optional ---
export OIDC_PROVIDER_NAME="OHSU Login"     # button label; default "Single Sign-On"
export OIDC_SCOPES="openid email profile"  # openid is always added
export OIDC_ALLOWED_DOMAINS=ohsu.edu       # comma-separated; empty = any
export OIDC_REQUIRE_VERIFIED_EMAIL=true    # default true
export OIDC_AUTO_PROVISION=false           # create accounts on first SSO login
export OIDC_AUTO_ACTIVATE=false            # ...and let them in without approval
export OIDC_RP_LOGOUT=false                # also end the session at the IdP

# --- deployment plumbing (matters for SSO, see below) ---
export TRUSTED_PROXY_COUNT=1               # reverse-proxy hops in front of Flask
export SESSION_COOKIE_SECURE=true          # set false only for plain-http dev
```

Add the same block to the `web` service's `environment:` list in your
`docker-compose.yml` (the worker needs none of it — background jobs don't
authenticate).

### The two plumbing variables

These trip up almost every first OIDC deployment, so they are worth
understanding rather than copying:

**`TRUSTED_PROXY_COUNT`.** The app runs behind a TLS-terminating
reverse proxy, so Flask itself sees plain HTTP on an internal hostname.
Left alone it would build the callback URI as
`http://flask:5000/auth/sso/callback`, which the provider rejects —
the registered URI is `https://`. `ProxyFix` makes `url_for(...,
_external=True)` honour the `X-Forwarded-Proto` / `-Host` headers the
proxy sets. Set it to the number of proxies actually in front of the
app (1 for the standard nginx-in-front-of-gunicorn layout), or `0` if
the app is directly exposed — trusting those headers with no proxy
present lets a client forge them.

**`SESSION_COOKIE_SECURE`.** On by default. The OIDC `state` and `nonce`
that secure the exchange ride in the session cookie, so it must survive
the round trip out to the provider and back — which is also why
`SameSite` is `Lax` and not `Strict`. Clear this only for a local
plain-HTTP dev instance, where a `Secure` cookie would never be sent at
all.

---

## Migration

The two identity columns ship in `e1b4d7c3a920`:

```sh
alembic upgrade head
```

Nothing about existing accounts changes — both columns are NULL, the
unique constraint on the pair tolerates any number of NULL rows, and
every user keeps signing in with their password exactly as before.

---

## Trying it out

1. `pip install -e ".[gui]"` (pulls in Authlib).
2. Set the `OIDC_*` variables and restart the app.
3. The login page grows a "Sign in with …" button above the password
   form. Missing? The config is incomplete — `enabled` requires client
   id, secret, *and* a discovery URL.
4. Sign in with an institutional account whose email matches an existing
   Colony Manager user. That first login writes the link; check it in
   Postgres:

   ```sql
   SELECT email, oidc_issuer, oidc_subject FROM "user" WHERE oidc_subject IS NOT NULL;
   ```

The admin user list shows an `SSO` and/or `Password` badge per account
once a provider is configured, so you can see at a glance who has
migrated.

### When it fails

| Symptom | Cause |
| --- | --- |
| Provider shows "redirect_uri mismatch" | The registered URI doesn't match what `url_for(_external=True)` built — almost always `TRUSTED_PROXY_COUNT` being wrong, giving `http://` instead of `https://` |
| "Single sign-on failed. Please try again." | Token exchange or ID-token validation failed; the real reason is in the app log (`OIDC token exchange failed: …`) |
| "mismatching_state" in the log | The session cookie didn't survive the round trip — check `SESSION_COOKIE_SECURE` against whether you're actually on HTTPS |
| "did not return an email address" | The `email` scope isn't granted, or the address is in a claim the app doesn't read — see the claims question above |
| "No Colony Manager account exists for …" | Expected with `OIDC_AUTO_PROVISION` off; create the account first |

---

## Security notes

- **The local password path is unchanged.** `check_password` returns
  False for an account with no hash, so an SSO-provisioned account can't
  be signed into with an empty or guessed password.
- **Linking is one-directional and permanent.** Nothing in the UI
  unlinks an account; do it in SQL (`UPDATE "user" SET oidc_subject =
  NULL, oidc_issuer = NULL WHERE …`) if you need to.
- **The `active` flag still governs everything.** SSO doesn't bypass
  admin approval, and the global `check_login` hook logs out a user
  deactivated mid-session on their next request, SSO or not.
- **`OIDC_AUTO_PROVISION` + `OIDC_AUTO_ACTIVATE` together mean "anyone
  the university vouches for may use this app."** That may well be what
  you want on a departmental instance — just make it a decision rather
  than a default, and pair it with `OIDC_ALLOWED_DOMAINS`.
