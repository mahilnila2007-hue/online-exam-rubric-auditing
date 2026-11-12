"""Firebase Admin SDK initialization and accessor utilities."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask, current_app

from app.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


class FirebaseManager:
    """Manages Firebase Admin app, Firestore client, Auth client, and Storage bucket."""

    def __init__(self) -> None:
        self._initialized = False
        self._configured = False
        self._error_message: str | None = None
        self._app = None
        self._db = None
        self._auth = None
        self._bucket = None

    def init_app(self, app: Flask) -> None:
        """Initialize Firebase Admin SDK from Flask configuration if credentials exist."""
        self._initialized = False
        self._configured = False
        self._error_message = None
        self._app = None
        self._db = None
        self._auth = None
        self._bucket = None

        if app.config.get("TESTING"):
            # Tests inject explicit repository / auth clients via app extensions.
            return

        project_id = app.config.get("FIREBASE_PROJECT_ID") or ""
        cred_path = app.config.get("FIREBASE_CREDENTIALS_PATH") or ""
        inline_json = app.config.get("FIREBASE_SERVICE_ACCOUNT_JSON") or ""
        storage_bucket = app.config.get("FIREBASE_STORAGE_BUCKET") or ""
        auth_emulator = app.config.get("FIREBASE_AUTH_EMULATOR_HOST") or ""
        firestore_emulator = app.config.get("FIRESTORE_EMULATOR_HOST") or ""

        if auth_emulator:
            os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = auth_emulator
        if firestore_emulator:
            os.environ["FIRESTORE_EMULATOR_HOST"] = firestore_emulator

        has_emulator = bool(auth_emulator or firestore_emulator)

        root_dir = Path(app.root_path).parent
        resolved_cred_file: Path | None = None
        if cred_path:
            candidate = Path(cred_path).expanduser()
            if not candidate.is_absolute():
                candidate = root_dir / candidate
            if candidate.is_file():
                resolved_cred_file = candidate

        # Convenience auto-discovery if user dropped a Firebase Admin SDK JSON into ./secrets/
        if resolved_cred_file is None:
            secrets_dir = root_dir / "secrets"
            if secrets_dir.is_dir():
                for json_file in sorted(secrets_dir.glob("*.json")):
                    try:
                        with json_file.open("r", encoding="utf-8") as handle:
                            meta = json.load(handle)
                        if meta.get("type") == "service_account":
                            resolved_cred_file = json_file
                            break
                    except Exception:
                        continue

        has_creds = bool(inline_json or resolved_cred_file is not None)

        if not has_creds and not has_emulator:
            self._error_message = (
                "Firebase Admin SDK is not configured. Download your Firebase Service Account JSON "
                "from Project Settings -> Service Accounts and save it in ./secrets/serviceAccountKey.json "
                "(or set FIREBASE_CREDENTIALS_PATH / FIREBASE_SERVICE_ACCOUNT_JSON in .env)."
            )
            logger.warning(self._error_message)
            return

        try:
            import firebase_admin
            from firebase_admin import auth as fb_auth
            from firebase_admin import credentials, firestore, storage
        except ImportError as exc:
            self._error_message = f"firebase-admin package is not installed: {exc}"
            logger.error(self._error_message)
            return

        try:
            cred = None
            if inline_json:
                service_account_info = json.loads(inline_json)
                cred = credentials.Certificate(service_account_info)
                project_id = project_id or service_account_info.get("project_id", "")
            elif resolved_cred_file is not None:
                cred = credentials.Certificate(str(resolved_cred_file))
                if not project_id:
                    with resolved_cred_file.open("r", encoding="utf-8") as handle:
                        project_id = json.load(handle).get("project_id", "")

            options: dict[str, Any] = {}
            if project_id:
                options["projectId"] = project_id
            if storage_bucket:
                options["storageBucket"] = storage_bucket

            if firebase_admin._apps:
                self._app = firebase_admin.get_app()
            elif cred is not None:
                self._app = firebase_admin.initialize_app(cred, options or None)
            else:
                # Emulator mode without service account certificate
                self._app = firebase_admin.initialize_app(options=options or {"projectId": project_id or "demo-exam-audit"})

            self._db = firestore.client(app=self._app)
            self._auth = fb_auth
            if storage_bucket:
                self._bucket = storage.bucket(app=self._app)

            self._configured = True
            self._initialized = True
            logger.info("Firebase Admin SDK initialized successfully (project=%s)", project_id or "default")
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            self._error_message = f"Failed to initialize Firebase Admin SDK: {exc}"
            logger.exception(self._error_message)

    @property
    def is_ready(self) -> bool:
        return self._configured and self._initialized

    @property
    def status(self) -> dict[str, Any]:
        return {
            "ready": self.is_ready,
            "configured": self._configured,
            "error": self._error_message,
            "emulator_mode": bool(
                os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or os.getenv("FIRESTORE_EMULATOR_HOST")
            ),
        }

    def require_db(self) -> Any:
        if not self.is_ready or self._db is None:
            raise ServiceUnavailableError(
                self._error_message or "Firestore database is unavailable. Check Firebase configuration.",
                error_code="FIREBASE_NOT_CONFIGURED",
            )
        return self._db

    def require_auth(self) -> Any:
        if not self.is_ready or self._auth is None:
            raise ServiceUnavailableError(
                self._error_message or "Firebase Authentication is unavailable. Check Firebase configuration.",
                error_code="FIREBASE_NOT_CONFIGURED",
            )
        return self._auth

    def get_bucket(self) -> Any:
        return self._bucket


firebase_manager = FirebaseManager()


def get_firebase_manager() -> FirebaseManager:
    return current_app.extensions.get("firebase_manager", firebase_manager)

