from pathlib import Path
import os
import json
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, "unsafe-default"),
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    USE_SQLITE=(bool, True),
    # Postgresql block (used when USE_SQLITE=False)
    POSTGRES_DB=(str, "pdf_manager"),
    POSTGRES_USER=(str, "postgres"),
    POSTGRES_PASSWORD=(str, "change_me"),
    POSTGRES_HOST=(str, "localhost"),
    POSTGRES_PORT=(str, "5432"),
    POSTGRES_CONN_MAX_AGE=(int, 60),
    # OCR Default Configurations
    OCR_ENABLED=(bool, True),
    OCR_LANG=(str, "eng"),
    OCR_DPI=(int, 300),
    OCR_MIN_TEXT_LENGTH=(int, 10),
    OCR_PYMUPDF_MIN_LENGTH=(int, 30),
    OCR_FORCE_CLIENT_LETTER=(bool, True),
    OCR_FORCE_BILL=(bool, True),
    OCR_CANDIDATE_TAG_LABELS=(list, []),  # may include "COVER" later
    OCR_TESSERACT_CMD=(str, ""),  # empty string = not yet set
    PARSER_DEBUG_OCR_PAGES=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    """
    Accept:
        - JSON list string: '["a", "b"]'
        - CSV string: "a,b"
        - single value: "a"
    """
    raw = os.getenv(name, "")
    if not raw:
        return default or []
    raw = raw.strip()

    # JSON list support
    if raw.startswith("[") and raw.endswith("["):
        try:
            val = json.loads(raw)
            if isinstance(val, list):
                return [str(x).strip() for x in val if str(x).strip()]
        except Exception:
            pass
    
    # CSV support
    if "," in raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    
    return [raw]


DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party app used to serve static files in development only
    "whitenoise.runserver_nostatic",
    # TODO: List project apps here when each app.py created
    "pdf_manager.apps.core",
    "pdf_manager.apps.parser",
    "pdf_manager.apps.ui",
    "pdf_manager.apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # used to server static files in development only
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "pdf_manager.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "pdf_manager.wsgi.application"

# DATABASES
#   SQLITE ALLOWED DURING EARLY DEVELOPMENT TO ALLOW FASTER DEV TIME
#   POSTGRESQL WILL BE USED IN PRODUCTION
USE_SQLITE = env("USE_SQLITE")

if USE_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",  # PostgreSQL is the chosen RDBSM
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env("POSTGRES_HOST"),
            "PORT": env("POSTGRES_PORT"),
            "CONN_MAX_AGE": env("POSTGRES_CONN_MAX_AGE"),
        }
    }

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Phase 4: Parsing Pipeline (data roots & limits) ---
DATA_ROOT = Path(env("DATA_ROOT", default=str(BASE_DIR / "data")))
INCOMING_DIR = DATA_ROOT / "incoming"
OUTPUTS_DIR = DATA_ROOT / "outputs"

# MVP: Enforce max size on ingestion (in MB)
MAX_UPLOAD_SIZE_MB = 25
ALLOWED_EXTENSIONS = {".pdf"}

# Ensure directories exist at startup (safe on repeated imports)
for _p in (DATA_ROOT, INCOMING_DIR, OUTPUTS_DIR):
    _p.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# OCR CONFIGURATION | See top of settings.py file for details
# ------------------------------------------------------------

# Global on/off switch for OCR
OCR_ENABLED = env("OCR_ENABLED")
# Basic OCR tuning
OCR_LANG = env("OCR_LANG")
OCR_DPI = env("OCR_DPI")
OCR_MIN_TEXT_LENGTH = env("OCR_MIN_TEXT_LENGTH")

# Controls when OCR is invoked in the regex field extractor
# - minimum pymupdf text length before we consider it "useable"
OCR_PYMUPDF_MIN_LENGTH = env("OCR_PYMUPDF_MIN_LENGTH")

# force OCR on high-value pages (ie client letter, bill_01) even if pymu returns usable text
OCR_FORCE_CLIENT_LETTER = env("OCR_FORCE_CLIENT_LETTER")
OCR_FORCE_BILL = env("OCR_FORCE_BILL")

# tag labels that are allowed to trigger OCR when pymupdf text too short
OCR_CANDIDATE_TAG_LABELS = env("OCR_CANDIDATE_TAG_LABELS")

OCR_TESSERACT_CMD = env("OCR_TESSERACT_CMD") or None

PARSER_DEBUG_OCR_PAGES = env("PARSER_DEBUG_OCR_PAGES")
