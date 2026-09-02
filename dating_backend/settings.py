import logging
from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv
import cloudinary
import dj_database_url

load_dotenv()

BASE_DIR   = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
# ✅ PRODUCTION: default flips to False. Before, forgetting to set the
# DEBUG env var on a new deploy silently left the app in debug mode —
# full tracebacks (with local variables, SQL, secrets in settings) shown
# to anyone who hits a 500. You now have to explicitly opt IN to debug
# mode, which is the safe default.
DEBUG      = os.getenv("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# ✅ PRODUCTION: these two are the classic "it worked in staging, then bit
# us in prod" foot-guns. We don't hard-crash the app over them (a bad env
# var shouldn't take the whole service down harder than the problem it's
# warning about), but we log loudly at startup so it shows up in your
# deploy logs instead of silently shipping an insecure config.
_startup_logger = logging.getLogger("django.security")
if ENVIRONMENT == "production":
    if SECRET_KEY == "change-this-in-production":
        _startup_logger.critical(
            "SECRET_KEY is still the placeholder value in production! "
            "Set a real SECRET_KEY env var immediately — sessions, "
            "password-reset tokens, and signed cookies are only as "
            "secure as this key."
        )
    if ALLOWED_HOSTS == ["*"]:
        _startup_logger.warning(
            "ALLOWED_HOSTS is '*' in production — this accepts requests "
            "with ANY Host header, which enables Host-header poisoning "
            "(cache poisoning, password-reset-link poisoning, etc). Set "
            "ALLOWED_HOSTS to your real domain(s), e.g. "
            "'dating-app-45za.onrender.com,api.yourdomain.com'."
        )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF      = "dating_backend.urls"
WSGI_APPLICATION  = "dating_backend.wsgi.application"
ASGI_APPLICATION  = "dating_backend.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# ── DATABASE ──
# ✅ PERF / DB-cost: without CONN_MAX_AGE, Django opens a brand-new
# TCP+TLS connection to Postgres on EVERY single request and tears it
# down at the end — that's pure overhead on every request's latency, and
# on Neon specifically it also means more connection churn against your
# compute (the thing the HealthView comment above is already trying to
# save). CONN_MAX_AGE=60 lets Django reuse a connection across requests
# for up to 60s; conn_health_checks pings it first so a connection Neon
# silently closed (e.g. after an autosuspend) doesn't surface as a
# broken-request error — Django just quietly opens a fresh one.
# NOTE: if you're on Neon's pooled connection string (PgBouncer, port
# 6543 / "-pooler" host), keep CONN_MAX_AGE at 0 instead — pooled
# connections shouldn't also be held open long-lived by Django itself.
if ENVIRONMENT == "production":
    DATABASES = {
        "default": dj_database_url.parse(
            os.getenv("DATABASE_URL"),
            conn_max_age=60,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "api.User"

# ✅ PRODUCTION: only length was checked before. RegisterSerializer uses
# a plain CharField (min_length=6) rather than Django's validators, so
# these aren't actually wired up yet — see the note in serializers.py.
# Listed here so they're one call away (`validate_password`) once wired.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── REST FRAMEWORK ──
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # ✅ PRODUCTION: baseline rate limiting for EVERY endpoint, not just
    # the auth ones. Without this, a single misbehaving client (bug in
    # the Flutter app, or someone scripting against the API) can hammer
    # /nearby/ or /search/ as fast as the network allows — each of those
    # hits are real DB queries. This is a safety net, separate from the
    # tighter AuthBurstThrottle already applied to login/register/OTP
    # views in views.py.
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
        # Matches views.AuthBurstThrottle's scope — that class hardcodes
        # its own rate via get_rate() so this entry isn't strictly
        # required, but keeping it here means the rate can be tuned from
        # settings alone if you later remove that override.
        "auth_burst": "15/min",
    },
}

# ── JWT ──
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":    timedelta(days=1),
    "REFRESH_TOKEN_LIFETIME":   timedelta(days=30),
    "ROTATE_REFRESH_TOKENS":    True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES":        ("Bearer",),
}

# ── CHANNELS ──
# ✅ FIX #1: pehle REDIS_HOST/REDIS_PORT alag-alag the (default "127.0.0.1")
# — production mein "localhost" ka koi Redis nahi hota (Render pe har
# service apne alag container mein hai), aur agar Redis password-protected
# ho toh alag host/port tuple format password embed nahi kar sakta.
# Ab ek hi REDIS_URL env var use karo — Render ka "Internal Redis URL"
# copy-paste karke daal do, chahe usme password ho ya na ho, dono chalega.
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")

# ✅ FIX #2 (asli crash ki wajah): channels_redis background mein hamesha
# ek lambi "blocking read" (BRPOP) karta rehta hai naye messages ke liye
# wait karte hue. redis-py ke async client mein ek known bug/behaviour hai
# jahan `socket_timeout` in lambi blocking reads pe bhi apply ho jaata hai
# — is wajah se bilkul theek connection bhi beech mein
# "TimeoutError: Timeout reading from ..." maar deta tha, aur Channels
# poore WebSocket consumer ko crash kar deta tha (isi wajah se baar-baar
# reconnect ho raha tha).
# `socket_timeout: None` iss read-timeout ko poori tarah disable kar deta
# hai (sirf isi channel-layer connection ke liye, baaki app pe asar nahi),
# aur `retry_on_timeout` + `health_check_interval` connection ko surakshit
# banate hain agar network mein genuinely koi hiccup ho.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [{
                "address":               REDIS_URL,
                "socket_timeout":        None,
                "socket_connect_timeout": 5,
                "socket_keepalive":      True,
                "retry_on_timeout":      True,
                "health_check_interval": 30,
            }],
        },
    },
}

# ---------------- SECURITY (production only) ----------------
# ✅ PRODUCTION: none of these were set before. Gated on ENVIRONMENT
# (same flag DATABASES already uses) rather than DEBUG — DEBUG can be
# False during local testing too, and forcing HTTPS-redirect / secure
# cookies there would break `runserver` over plain http://.
if ENVIRONMENT == "production":
    # Render (and most PaaS) terminate TLS at a proxy and forward plain
    # HTTP internally with an X-Forwarded-Proto header — without this,
    # Django thinks every request is insecure (request.is_secure() is
    # always False), which breaks SECURE_SSL_REDIRECT and secure-cookie
    # logic below.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT     = True

    # JWT auth means the API itself doesn't rely on cookies, but Django
    # admin and the session/CSRF middleware still use them — make sure
    # those are never sent over plain HTTP and never readable by JS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE    = True
    SESSION_COOKIE_HTTPONLY = True

    # HSTS tells browsers to remember "always use HTTPS for this domain"
    # for a year, and to include subdomains — standard hardening once
    # you're confident everything is served over TLS.
    SECURE_HSTS_SECONDS            = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD            = True

    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS             = "DENY"

# ---------------- CORS ----------------

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:8000",
        "https://dating-app-45za.onrender.com",
    ]

CORS_ALLOW_HEADERS = [
    "authorization",
    "content-type",
    "accept",
]

# ── CLOUDINARY ✅ ──
cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key    = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure     = True,
)

# ── MEDIA (local fallback) ──
MEDIA_URL  = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ── STATIC ──
STATIC_URL  = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── LOGGING ──
# ✅ PRODUCTION: no LOGGING config existed before. Django's implicit
# default still prints to console, but WITHOUT this, logger.exception()
# calls (firebase_auth.py, consumers.py's group_send/DB-error handling,
# views.py's broadcast fallback) don't reliably show levels, timestamps,
# or module names, and a misconfigured logger can silently swallow
# warnings. This makes every log line consistent and easy to grep/ship
# to a log aggregator (Render logs, CloudWatch, etc. all just tail
# stdout, which is what the console handler writes to).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # Django's own request logger already logs 500s with tracebacks —
        # keep it, just don't let it flood INFO-level noise.
        "django": {
            "handlers": ["console"],
            "level": "INFO" if DEBUG else "WARNING",
            "propagate": False,
        },
        # Your app code (views.py, consumers.py, utils.py, firebase_auth.py
        # all use logging.getLogger(__name__), which nests under "api").
        "api": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ── I18N ──
LANGUAGE_CODE = "en-us"
TIME_ZONE     = "Asia/Kolkata"
USE_I18N      = True
USE_TZ        = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"