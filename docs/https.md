# Serving Colony Manager over HTTPS

Short version: **the application does not terminate TLS, and shouldn't.**
Gunicorn serves plain HTTP on port 5000 inside the container, published
as 9001 on the NAS. Something in front of it terminates TLS and forwards
the request, and the app's job is to notice that this happened and build
its URLs accordingly.

That "notice" is already wired up — `ProxyFix` in the app factory, plus
`Secure` session cookies — so no application change is needed to move to
HTTPS. What's needed is the terminator in front, and the handful of
environment variables below.

This became a requirement rather than a nice-to-have with single sign-on:
identity providers will not register an `http://` redirect URI. See
`docs/sso.md`.

---

## Where TLS terminates

On the mmm NAS the stack is `db`, `redis`, `flask`, `rq-worker`,
`rq-dashboard` — there is no nginx or Caddy service, and there shouldn't
be one. DSM already binds ports 80 and 443 for its own web services, so
a TLS container added to the compose stack would fail to bind them.

Use **DSM's built-in reverse proxy** instead. It is nginx underneath, it
integrates with DSM's certificate store, and it already sets the
`X-Forwarded-*` headers `ProxyFix` reads.

### DSM setup

Control Panel → **Login Portal** → **Advanced** → **Reverse Proxy** →
Create:

| Field | Value |
| --- | --- |
| Description | Colony Manager |
| Source protocol | HTTPS |
| Source hostname | `colony.ohsu.edu` (whatever name the cert covers) |
| Source port | 443 |
| Destination protocol | HTTP |
| Destination hostname | `localhost` |
| Destination port | 9001 |

Then, on the **Custom Header** tab of that rule, click *Create* →
*WebSocket*. That adds the `Upgrade`/`Connection` headers. Colony
Manager doesn't use websockets today, but htmx long-polling and any
future live updates need them, and adding it later means remembering
this page exists.

Install the certificate under Control Panel → **Security** →
**Certificate**, then use *Settings* to bind it to the reverse-proxy
rule you just made. An OHSU-issued certificate goes in as *Add* →
*Import certificate*; Let's Encrypt is the other option if the host is
publicly resolvable.

### Closing the plain-HTTP door

Port 9001 stays published by docker-compose and remains reachable over
plain HTTP even once the proxy is up. Two things to do about it:

1. Set `CANONICAL_BASE_URL` (below) so anyone arriving there is
   redirected to the HTTPS name.
2. Consider dropping the `ports:` mapping for the `web` service in
   `docker-compose.yml` entirely, so the container is reachable only
   from the NAS host. DSM's reverse proxy talks to `localhost:9001`, so
   binding it as `"127.0.0.1:9001:5000"` keeps that working while taking
   it off the LAN — the same treatment `rq-dashboard` already gets.

Leaving it open is not just untidy. The session cookie is `Secure`, so a
browser on the plain-HTTP URL never sends it; sign-in then fails with
`mismatching_state` and nothing in the error points at the URL being the
problem.

---

## Environment variables

```sh
# The public origin. Any request on a different scheme or host is
# 308-redirected here. Also supplies the scheme when a URL has to be
# built outside a request (CLI, background jobs).
export CANONICAL_BASE_URL=https://colony.ohsu.edu

# Reverse-proxy hops in front of the app. DSM's reverse proxy is one.
# Set to 0 if the app is ever exposed directly — see the warning below.
export TRUSTED_PROXY_COUNT=1

# Leave unset (the default is on). Only clear it for a plain-http dev box.
# export SESSION_COOKIE_SECURE=false

# HSTS. Off by default; turn on only once HTTPS is known good.
# export HSTS_SECONDS=31536000
```

### ⚠️ `TRUSTED_PROXY_COUNT` must match reality

`ProxyFix` *believes* the `X-Forwarded-*` headers. That is correct when a
proxy sets them and strips any the client sent, and wrong when there is
no proxy — then any client can send `X-Forwarded-Proto: https` and the
app will believe the connection is secure.

The default is `1`, which assumes the DSM reverse proxy is in place. **If
you deploy before configuring the proxy, set `TRUSTED_PROXY_COUNT=0`**
until it's up. The risk on an internal NAS is modest, but the setting
should describe the deployment, not the intention.

### HSTS is one-way

`HSTS_SECONDS` sends `Strict-Transport-Security`. Once a browser has seen
it, that browser refuses plain HTTP to the host for the full max-age and
the server cannot take it back — clearing the header does nothing for
anyone who already has it cached. Enable it after HTTPS has been working
for a while, and start with a short max-age (`3600`) before going to a
year.

It is only sent on requests that actually arrived over HTTPS, so it
cannot be triggered accidentally from a dev box.

---

## Verifying

```sh
# Certificate and protocol
curl -sSI https://colony.ohsu.edu/auth/login | head -1

# The redirect off the plain-http port
curl -sSI http://mmm.ohsu.edu:9001/auth/login | grep -i 'HTTP/\|location'
#   HTTP/1.1 308 PERMANENT REDIRECT
#   Location: https://colony.ohsu.edu/auth/login

# Session cookie must come back marked Secure
curl -sSI https://colony.ohsu.edu/auth/login | grep -i set-cookie
```

The one that actually matters for SSO is the callback URI the app
builds, since it must equal the URI registered with the provider
character for character:

```sh
ssh mmm 'cd /volume2/docker/flask && /usr/local/bin/docker-compose exec -T web \
    python -c "
from colony_manager_gui import create_app
from flask import url_for
app = create_app()
with app.test_request_context(\"/\", base_url=\"https://colony.ohsu.edu\"):
    print(url_for(\"auth.sso_callback\", _external=True))
"'
```

If that prints `http://…` or an internal hostname, `TRUSTED_PROXY_COUNT`
or `CANONICAL_BASE_URL` is wrong, and SSO will fail with a
`redirect_uri` mismatch at the provider.

---

## Local development

The `Secure` cookie default means plain `http://localhost:5000` can't
hold a session. Either opt out:

```sh
SESSION_COOKIE_SECURE=false python run.py
```

...or run the dev server over TLS. A throwaway self-signed cert:

```sh
FLASK_SSL=1 python run.py        # browser will warn; fine for local use
```

A locally-trusted cert, which you'll want if you're testing the real SSO
round trip (providers generally won't redirect to a self-signed host):

```sh
mkcert -install && mkcert localhost
FLASK_SSL_CERT=localhost.pem FLASK_SSL_KEY=localhost-key.pem python run.py
```

Either way the redirect URI becomes `https://localhost:5000/auth/sso/callback`,
which has to be registered with the provider as a second URI before it
will work.
