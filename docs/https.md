# Serving Colony Manager over HTTPS

Short version: **the application does not terminate TLS, and shouldn't.**
Gunicorn serves plain HTTP on port 5000 inside the container. Something
in front terminates TLS and forwards the request, and the app's job is to
notice that happened and build its URLs accordingly.

That "notice" is already wired up — `ProxyFix` in the app factory, plus
`Secure` session cookies — so no application change is needed. What's
needed is the terminator in front, and the environment variables below.

This became a requirement rather than a nice-to-have with single sign-on:
identity providers will not register an `http://` redirect URI. See
`docs/sso.md`.

---

## The mmm deployment

| Port | Bound by | Serving |
| --- | --- | --- |
| 443 | DSM nginx | redirects to DSM's own UI on 5001 |
| 5000 / 5001 | DSM | DSM administration |
| **9443** | DSM reverse proxy | **HTTPS — the public URL** |
| **9002** | Docker | gunicorn, plain HTTP — deliberate fallback, see below |

TLS terminates at **DSM's reverse proxy**, not a container. DSM already
binds 80 and 443, so an nginx or Caddy service in the compose stack could
not bind them. DSM's proxy is nginx underneath, integrates with DSM's
certificate store, and sets the `X-Forwarded-*` headers `ProxyFix` reads.

The public URL is **`https://mmm.ohsu.edu:9443`**.

### Why 9443 and not 443 or 9001

443 is DSM's own UI and cannot be taken over.

9001 — the port the container originally published, and the obvious
choice for preserving bookmarks — was refused by DSM's reverse-proxy
form with *"This port number is used by another application"*, even with
nothing listening on it and no reference to it anywhere in DSM's config,
nginx's config, or any package's port registry. DSM reserves it
somewhere not visible from the filesystem. Not worth fighting; 9443 is
the conventional "HTTPS on a non-standard port" choice.

The certificate already installed covers `mmm.ohsu.edu` and nothing else
(`CN = mmm.ohsu.edu`, InCommon, to Jan 2027), which is why the hostname
stayed put and a separate `colony.ohsu.edu` was not pursued — that would
have needed a new DNS record *and* a new certificate request.

### The plain-HTTP fallback on 9002

`http://mmm.ohsu.edu:9002` is left open across the LAN **on purpose**, so
the lab can still reach the app if DSM's reverse proxy or its certificate
fails. This is a deliberate availability-over-hardening trade, not an
oversight.

It has a consequence that has to be understood, because the fallback does
not work by default:

**`SESSION_COOKIE_SECURE` is on by default, and a `Secure` cookie is
never sent over plain HTTP.** So on `:9002` the browser will not store or
return the session cookie, and *login fails* — you get the login page,
submit it, and land back on the login page. The port being reachable is
not the same as the fallback working.

Two ways to resolve it, and the choice is a real one:

| | Fallback works | Cost |
| --- | --- | --- |
| `SESSION_COOKIE_SECURE=false` permanently | yes, always | the session cookie is sent in clear on `:9002`, and is strippable on the LAN |
| Leave it on; flip it in an emergency | only after a restart | one env var + `docker-compose up -d web`, ~30 seconds |

The second is recommended and is what the environment below assumes. A
restart is already part of any response to "the proxy is broken", so the
lever costs little at the moment you need it, and you are not carrying an
unprotected cookie for the 99% of the time the proxy is fine.

**Do not set `CANONICAL_BASE_URL` while you want this fallback.** It
308-redirects anything arriving over plain HTTP to the HTTPS origin,
which is precisely what a fallback user is trying to avoid. The two
features are mutually exclusive by design; pick one.

---

## Environment

In the `web` service's `environment:`:

```sh
TRUSTED_PROXY_COUNT=1
# CANONICAL_BASE_URL — intentionally unset; see the fallback section.
# SESSION_COOKIE_SECURE — intentionally unset (defaults true); the
#   emergency lever is to set it false and restart.
# HSTS_SECONDS — off; see below.
```

### ⚠️ `TRUSTED_PROXY_COUNT` must match reality

`ProxyFix` *believes* `X-Forwarded-*`. That is correct when a proxy sets
those headers and strips any the client sent, and wrong when there is no
proxy — then any client can send `X-Forwarded-Proto: https` and the app
will believe the connection is secure.

Note the interaction with the 9002 fallback: requests arriving there do
**not** pass through DSM, so a client can forge those headers on that
port. The app will then build `https://` URLs for a plain-HTTP session.
That is survivable for an emergency fallback, but it is the reason the
fallback port should not be exposed beyond the LAN.

### HSTS is one-way

`HSTS_SECONDS` sends `Strict-Transport-Security`. Once a browser has seen
it, that browser refuses plain HTTP to the host for the full max-age and
the server cannot take it back — clearing the header does nothing for
anyone who already has it cached.

**Do not enable it on this deployment.** HSTS applies to the *host*, not
the port, so it would forbid plain HTTP to `mmm.ohsu.edu` entirely — which
would kill the 9002 fallback permanently in every browser that had
visited the site, exactly when you need it. It would also cover DSM's own
UI on 5000.

---

## The canonical-redirect loop

Only relevant if you ever set `CANONICAL_BASE_URL`. Recorded because the
failure is opaque and the fix is non-obvious.

The redirect is keyed on **the request scheme alone, never the host or
port**. The tempting implementation compares `request.host` against the
canonical origin's `host:port` and redirects on any mismatch. That loops,
and a non-standard port like 9443 makes it near-certain: whether the app
can see the public `host:port` depends entirely on what the proxy puts in
`Host` / `X-Forwarded-Host`. nginx's `$host` drops a non-default port;
some configurations forward the *backend* address instead. Any of those
makes the comparison mismatch forever — redirect to the canonical URL,
proxy forwards it back with the same unexpected `Host`, redirect again.

### Reproducing it

The committed version at `9d2ae32` has the host-comparison form; the
working tree has the scheme-only fix. To see the difference, from the
worktree:

```sh
cp src/colony_manager_gui/__init__.py /tmp/with-fix.py
git checkout -- src/colony_manager_gui/__init__.py     # back to the buggy version
```

Run the dev server (see below) with a canonical URL that carries a port:

```sh
CANONICAL_BASE_URL=https://localhost:9443 SESSION_COOKIE_SECURE=false python run.py
```

Then send the request a proxy would send — https, but with a `Host` that
has lost its port:

```sh
curl -sSI -H 'X-Forwarded-Proto: https' -H 'X-Forwarded-Host: localhost' \
     http://localhost:5000/auth/login | head -2
```

Buggy version:

```
HTTP/1.1 308 PERMANENT REDIRECT
Location: https://localhost:9443/auth/login
```

That 308 *is* the loop. The request already claims to be HTTPS on the
canonical origin, and the app is redirecting it back to where it came
from — so the proxy re-forwards it identically, forever. A browser gives
up with `ERR_TOO_MANY_REDIRECTS`.

Restore the fix and the same request returns `200`:

```sh
cp /tmp/with-fix.py src/colony_manager_gui/__init__.py
```

The automated version of the same check is parametrised over all three
`Host` shapes:

```sh
pytest tests/test_https.py -k whatever_host -v
```

Run it against the buggy file and all three fail; against the fix, all
three pass.

---

## Verifying the deployment

```sh
# HTTPS works and does not loop
curl -sSI https://mmm.ohsu.edu:9443/auth/login | head -1

# Session cookie comes back marked Secure
curl -sSI https://mmm.ohsu.edu:9443/auth/login | grep -i set-cookie

# The fallback port answers (login there needs the lever above)
curl -sSI http://mmm.ohsu.edu:9002/auth/login | head -1
```

The check that matters for SSO is the callback URI the app builds, which
must equal the URI registered with the provider character for character:

```sh
ssh mmm 'cd /volume2/docker/flask && /usr/local/bin/docker-compose exec -T web \
    python -c "
from colony_manager_gui import create_app
from flask import url_for
app = create_app()
with app.test_request_context(\"/\", base_url=\"https://mmm.ohsu.edu:9443\"):
    print(url_for(\"auth.sso_callback\", _external=True))
"'
#   expect: https://mmm.ohsu.edu:9443/auth/sso/callback
```

If that prints `http://` or an internal hostname, `TRUSTED_PROXY_COUNT`
is wrong and SSO will fail with a `redirect_uri` mismatch at the
provider.

---

## Running a dev server from a worktree

The catch: `colony-manager` is **pip-installed editable against the main
checkout**, so `import colony_manager_gui` resolves to
`src/colony-manager/src/...` no matter which worktree you are standing
in. Running `python run.py` from a worktree silently runs main's code.

Put the worktree's `src` on `PYTHONPATH` to shadow it:

```sh
cd /c/Users/buran/projects/colony-manager/src/colony-manager/.claude/worktrees/oidc-sso
export PYTHONPATH="$PWD/src"
python -c "import colony_manager_gui; print(colony_manager_gui.__file__)"   # confirm
```

That last line must print a path under `.claude/worktrees/...`. If it
doesn't, nothing else here is testing what you think it is.

### Environment

```sh
source /c/Users/buran/bin/anaconda3/etc/profile.d/conda.sh
conda activate colony-manager           # has mmm_db; needs Authlib installed once:
pip install "Authlib>=1.3" "requests>=2.28"

export PYTHONPATH="$PWD/src"
export SECRET_KEY=dev
export DATABASE_URL=postgresql+psycopg2://...     # NOT production, see below
export SESSION_COOKIE_SECURE=false                # plain-http dev server
python run.py
```

`colony-manager-test` has Authlib but not `mmm_db`, so the data-file
features won't load there. `colony-manager` has `mmm_db` but needs the
two packages above installed once. (CLAUDE.md still refers to a
`gerbil-manager` env; that no longer exists.)

### ⚠️ Use a scratch database, not production

This branch adds `oidc_issuer` / `oidc_subject` to `user` (migration
`e1b4d7c3a920`). The models select those columns, so pointing a dev
server at a database that has not been migrated fails every query
touching `User` — including login — with `UndefinedColumn`.

Clone a scratch database and migrate that:

```sh
createdb -T colony_manager colony_manager_dev     # or pg_dump/restore
DATABASE_URL=postgresql+psycopg2://.../colony_manager_dev alembic upgrade head
```

The migration itself is additive and safe to run against production early
— it only adds two nullable columns, and the currently-deployed code
neither selects nor writes them — but a dev *server* pointed at
production is a different risk and not worth taking.

### Dev server over TLS

Needed to exercise the real SSO round trip, and because a `Secure`
cookie can't work over plain HTTP. A throwaway self-signed cert:

```sh
FLASK_SSL=1 python run.py        # browser will warn; fine for local use
```

A locally-trusted cert, which most providers will require before they
redirect back to your laptop:

```sh
mkcert -install && mkcert localhost
FLASK_SSL_CERT=localhost.pem FLASK_SSL_KEY=localhost-key.pem python run.py
```

Either way the redirect URI becomes `https://localhost:5000/auth/sso/callback`,
which has to be registered with the provider as a second URI first.
