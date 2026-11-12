"""Application configuration management using environment variables."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    """Base configuration shared across all environments."""

    APP_NAME = "Online Examination System with Rubric Auditing Mechanism"
    APP_SHORT_NAME = "RubriAssess"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-before-production")

    # Session & Cookie Security (keep Flask's CSRF cookie separate from Firebase auth cookie)
    SESSION_COOKIE_NAME = os.getenv("FLASK_SESSION_COOKIE_NAME", "rubriassess_csrf_session")
    FIREBASE_SESSION_COOKIE_NAME = os.getenv("FIREBASE_SESSION_COOKIE_NAME", "rubriassess_fb_session")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _parse_bool(os.getenv("SESSION_COOKIE_SECURE"), False)
    SESSION_DURATION_HOURS = int(os.getenv("SESSION_DURATION_HOURS", "12"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=SESSION_DURATION_HOURS)

    # Firebase Admin Configuration (Server-only)
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "").strip()
    FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()

    # Optional Firebase Local Emulators
    FIREBASE_AUTH_EMULATOR_HOST = os.getenv("FIREBASE_AUTH_EMULATOR_HOST", "").strip()
    FIRESTORE_EMULATOR_HOST = os.getenv("FIRESTORE_EMULATOR_HOST", "").strip()

    # Firebase Public Web Config (Safe for client JS)
    FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "").strip()
    FIREBASE_WEB_AUTH_DOMAIN = os.getenv("FIREBASE_WEB_AUTH_DOMAIN", "").strip()
    FIREBASE_WEB_PROJECT_ID = os.getenv("FIREBASE_WEB_PROJECT_ID", "").strip() or FIREBASE_PROJECT_ID
    FIREBASE_WEB_STORAGE_BUCKET = os.getenv("FIREBASE_WEB_STORAGE_BUCKET", "").strip()
    FIREBASE_WEB_MESSAGING_SENDER_ID = os.getenv("FIREBASE_WEB_MESSAGING_SENDER_ID", "").strip()
    FIREBASE_WEB_APP_ID = os.getenv("FIREBASE_WEB_APP_ID", "").strip()
    FIREBASE_WEB_MEASUREMENT_ID = os.getenv("FIREBASE_WEB_MEASUREMENT_ID", "").strip()

    # Upload & Examination Policy
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", "10")) * 1024 * 1024
    EXAM_SUBMIT_GRACE_SECONDS = int(os.getenv("EXAM_SUBMIT_GRACE_SECONDS", "30"))
    MAX_QUESTION_OPTIONS = 6
    MIN_QUESTION_OPTIONS = 2

    TESTING = False

    @classmethod
    def get_firebase_web_config(cls) -> dict[str, str]:
        """Return strictly public Firebase Web SDK configuration values."""
        return {
            "apiKey": os.getenv("FIREBASE_WEB_API_KEY", cls.FIREBASE_WEB_API_KEY).strip(),
            "authDomain": os.getenv("FIREBASE_WEB_AUTH_DOMAIN", cls.FIREBASE_WEB_AUTH_DOMAIN).strip(),
            "projectId": (
                os.getenv("FIREBASE_WEB_PROJECT_ID", "").strip()
                or os.getenv("FIREBASE_PROJECT_ID", cls.FIREBASE_PROJECT_ID).strip()
            ),
            "storageBucket": os.getenv("FIREBASE_WEB_STORAGE_BUCKET", cls.FIREBASE_WEB_STORAGE_BUCKET).strip(),
            "messagingSenderId": os.getenv(
                "FIREBASE_WEB_MESSAGING_SENDER_ID", cls.FIREBASE_WEB_MESSAGING_SENDER_ID
            ).strip(),
            "appId": os.getenv("FIREBASE_WEB_APP_ID", cls.FIREBASE_WEB_APP_ID).strip(),
            "measurementId": os.getenv("FIREBASE_WEB_MEASUREMENT_ID", cls.FIREBASE_WEB_MEASUREMENT_ID).strip(),
            "authEmulatorHost": os.getenv("FIREBASE_AUTH_EMULATOR_HOST", cls.FIREBASE_AUTH_EMULATOR_HOST).strip(),
        }


class DevelopmentConfig(BaseConfig):
    """Local development configuration."""

    DEBUG = _parse_bool(os.getenv("FLASK_DEBUG"), False)


class ProductionConfig(BaseConfig):
    """Production hardening defaults."""

    DEBUG = False
    SESSION_COOKIE_SECURE = _parse_bool(os.getenv("SESSION_COOKIE_SECURE"), True)


class TestingConfig(BaseConfig):
    """Automated test suite configuration."""

    TESTING = True
    SECRET_KEY = "test-suite-secret-key"
    SESSION_COOKIE_SECURE = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def resolve_config(env_name: str | None = None) -> type[BaseConfig]:
    name = (env_name or os.getenv("FLASK_ENV") or "development").strip().lower()
    return CONFIG_MAP.get(name, DevelopmentConfig)
