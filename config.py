import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

# One database location for every environment unless DATABASE_URL overrides it.
# Development and production previously disagreed (instance/vms.db vs ./vms.db),
# so a production boot with no DATABASE_URL silently opened a second, empty
# database next to the real one and 500'd on the first write.
DEFAULT_DB_PATH = os.path.join(basedir, "instance", "vms.db")
DEFAULT_DB_URI = "sqlite:///" + DEFAULT_DB_PATH


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    VMS_PER_PAGE = 15
    # Display currency for every cost field (label + Jinja `currency` filter).
    CURRENCY = os.environ.get("CURRENCY", "USD")
    CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "$")

    # --- session hardening ------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True      # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE = "Lax"     # not sent on cross-site POSTs
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_REFRESH_EACH_REQUEST = True

    # --- reverse proxy ----------------------------------------------------
    # How many proxy hops sit in front of the app. 0 (the default) means
    # "not behind a proxy": client-supplied X-Forwarded-* headers are IGNORED
    # and request.remote_addr stays the real socket peer. That is the safe
    # default because any client can send a forged X-Forwarded-For header,
    # which would otherwise let it change its apparent IP on every request
    # and walk straight past the login throttle.
    #
    # Behind nginx/Caddy set TRUSTED_PROXY_HOPS=1 (2 if there is a CDN or
    # load balancer in front of the proxy). app/__init__.py then installs
    # werkzeug's ProxyFix for exactly that many hops, and request.remote_addr
    # becomes the real client address the proxy reported.
    TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))


class DevConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False       # localhost is plain http
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", DEFAULT_DB_URI)


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Flask-WTF's documented test setting: tokens are generated but not
    # enforced, so route tests don't each have to mint a token. tests/
    # test_security.py re-enables it on a purpose-built app to prove the
    # guard actually rejects missing/forged tokens.
    WTF_CSRF_ENABLED = False
    # Sessions are still real in tests (the client fixture logs in); this
    # only relaxes CSRF, never authentication.
    SERVER_NAME = "localhost"


class ProdConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True        # never send the session over plain http
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", DEFAULT_DB_URI)


config = {
    "development": DevConfig,
    "testing": TestConfig,
    "production": ProdConfig,
}
