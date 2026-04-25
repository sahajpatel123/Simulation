"""
Ensure required env is present before app modules load `app.core.config.settings`
(which instantiates Settings() at import time and requires DATABASE_URL).
"""

from __future__ import annotations

import os

# Default: local dev / CI placeholder — override with a real URL when running integration tests.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/thecee",
)
