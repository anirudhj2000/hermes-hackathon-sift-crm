"""
Django settings for the agentic-crm project.

Loads environment variables from the repo-root .env (see ../.env.example
and CONTRACTS.md).
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load repo-root .env (agentic-crm/.env)
load_dotenv(BASE_DIR.parent / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-_*(&l#-1w0*ve@!g_58*w%y2@f-z76qlz71n5zs0ma0q*9)x-@"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "crm",
    "agentcore",
    "pipelines",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", "postgres://localhost:5432/agentic_crm"),
    )
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# DRF

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}


# CORS (Vite dev server)

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


# Agentic CRM settings (defaults per CONTRACTS.md)

HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")
HERMES_BASE_URL = os.environ.get("HERMES_BASE_URL", "https://inference.nousresearch.com/v1")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "Hermes-4-405B")
COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
SIDECAR_URL = os.environ.get("SIDECAR_URL", "http://localhost:3001")
INGEST_SECRET = os.environ.get("INGEST_SECRET", "dev-ingest-secret")

# Langfuse observability — the SDK reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
# / LANGFUSE_HOST from the environment (loaded from .env above). When the keys
# are unset, agentcore.tracing no-ops so the offline demo keeps working.
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

# Agent workspace — the agent's filesystem world (connectors, schemas,
# workflows, run summaries). Default: <repo>/workspace.
AGENT_WORKSPACE_ROOT = os.environ.get(
    "AGENT_WORKSPACE_ROOT", str(BASE_DIR.parent / "workspace")
)
