from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv
import cloudinary
import dj_database_url

load_dotenv()

BASE_DIR   = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
DEBUG      = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

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

if ENVIRONMENT == "production":
    DATABASES = {
        "default": dj_database_url.parse(os.getenv("DATABASE_URL"))
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "api.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 6}},
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

# ---------------- CORS ----------------

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
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

# ── I18N ──
LANGUAGE_CODE = "en-us"
TIME_ZONE     = "Asia/Kolkata"
USE_I18N      = True
USE_TZ        = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"