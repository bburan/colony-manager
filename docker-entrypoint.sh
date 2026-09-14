#!/bin/sh
set -e

# docker-compose bind-mounts the live source tree over /app at container
# start, which shadows whatever `pip install -e` produced in the image at
# build time (setuptools_scm-generated version.py, .egg-info/, etc). Those
# generated files are gitignored on purpose, so they never exist on the
# host. Regenerate them here, against the code that's actually mounted,
# before dropping to the unprivileged runtime user.
if [ "$(id -u)" = "0" ]; then
    pip install --no-deps -e "./colony-manager[gui]" -e "./mmm-db" -e "./cftsdata"
    chown -R mmm:synousers /app
    exec setpriv --reuid=1027 --regid=100 --clear-groups "$@"
fi

exec "$@"
