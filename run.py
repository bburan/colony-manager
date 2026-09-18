import os

from colony_manager_gui import create_app

# Instantiate the application using the factory function
app = create_app()


def _flag(name, default='0'):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes')


if __name__ == '__main__':
    debug = _flag('FLASK_DEBUG')

    # Local HTTPS for the dev server. Worth having because the session
    # cookie is ``Secure`` by default: over plain http the browser drops
    # it, and the OIDC sign-in fails with ``mismatching_state`` rather
    # than anything that points at the cause. ``adhoc`` makes werkzeug
    # mint a throwaway self-signed certificate at startup (needs
    # ``cryptography``, which Authlib already pulls in) — the browser
    # will warn about it, which is fine for a dev box but means most
    # identity providers won't accept it as a redirect target.
    #
    # The alternative, when a provider does need to redirect back to your
    # laptop, is a locally-trusted cert from mkcert:
    #     mkcert -install && mkcert localhost
    #     FLASK_SSL_CERT=localhost.pem FLASK_SSL_KEY=localhost-key.pem python run.py
    cert = os.environ.get('FLASK_SSL_CERT', '').strip()
    key = os.environ.get('FLASK_SSL_KEY', '').strip()
    if cert and key:
        ssl_context = (cert, key)
    elif _flag('FLASK_SSL'):
        ssl_context = 'adhoc'
    else:
        ssl_context = None

    app.run(host='0.0.0.0', port=5000, debug=debug, ssl_context=ssl_context)
