"""Development entrypoint for the Flask application."""

from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = bool(app.config.get("DEBUG", False))
    app.run(host="127.0.0.1", port=port, debug=debug)

