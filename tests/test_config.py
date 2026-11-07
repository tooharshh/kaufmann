from pathlib import Path

import pytest

from src.config import Settings


def test_invalid_database_url_is_redacted(monkeypatch, tmp_path: Path):
    for name in (
        "CEREBRAS_API_KEY",
        "SARVAM_API_KEY",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "SUPABASE_PUBLISHABLE_KEY",
    ):
        monkeypatch.setenv(name, "test-secret")
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.com")
    monkeypatch.setenv("SUPABASE_URL", "https://example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@[bad-host]:5432/db")
    with pytest.raises(ValueError, match="^Invalid URL: DATABASE_URL$"):
        Settings.load(tmp_path / "absent.env")
