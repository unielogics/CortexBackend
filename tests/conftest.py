"""
Pytest configuration. Ensures CI uses SQLite for deterministic, isolated runs.
Set DATABASE_URL to in-memory SQLite before app import. Unset MONGODB_URI to force SQLite.
"""
import os

# Run before any test module imports unie_cortex
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ.pop("MONGODB_URI", None)  # Force SQLite; config.use_mongodb will be False
