"""CLI script to provision an initial Admin or Examiner account in Firebase Auth & Firestore."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from app.extensions.firebase import get_firebase_manager


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provision an Admin or Examiner account in Firebase Auth and Firestore."
    )
    parser.add_argument("--email", required=True, help="Account email address")
    parser.add_argument("--name", required=True, help="Full display name")
    parser.add_argument("--role", default="admin", choices=["admin", "examiner", "student"])
    parser.add_argument("--institution-id", default="ADMIN-001", help="Institution / Faculty ID")
    parser.add_argument("--department", default="Academic Administration", help="Department name")
    parser.add_argument("--password", default="", help="Password (prompted securely if omitted)")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Enter password (min 8 chars): ")
    if len(password) < 8:
        print("Error: Password must be at least 8 characters.", file=sys.stderr)
        return 1

    app = create_app()
    with app.app_context():
        mgr = get_firebase_manager()
        if not mgr.is_ready:
            print(f"Error: {mgr.status.get('error')}", file=sys.stderr)
            return 1

        fb_auth = mgr.require_auth()
        user_repo = app.extensions["repositories"]["users"]

        email = args.email.strip().lower()
        try:
            fb_user = fb_auth.get_user_by_email(email)
            print(f"Found existing Firebase Auth user ({fb_user.uid}); updating claims & profile...")
        except Exception:
            fb_user = fb_auth.create_user(
                email=email,
                password=password,
                display_name=args.name.strip(),
            )
            print(f"Created Firebase Auth user ({fb_user.uid}).")

        fb_auth.set_custom_user_claims(fb_user.uid, {"role": args.role})
        now = datetime.now(timezone.utc)
        user_repo.set_merge(
            fb_user.uid,
            {
                "uid": fb_user.uid,
                "email": email,
                "full_name": args.name.strip(),
                "role": args.role,
                "institution_id": args.institution_id.strip(),
                "department": args.department.strip(),
                "status": "active",
                "created_at": now,
            },
        )
        print(f"Successfully provisioned {args.role} account for {email} (uid={fb_user.uid}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

