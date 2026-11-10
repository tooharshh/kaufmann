import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True, repr=False)
class Settings:
    values: dict[str, str] = field(repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        load_dotenv(path or Path(__file__).resolve().parents[1] / ".env")
        names = (
            "CEREBRAS_API_KEY",
            "SARVAM_API_KEY",
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "VOICE_DISPATCH_SECRET",
            "DATABASE_URL",
            "SUPABASE_URL",
            "SUPABASE_PUBLISHABLE_KEY",
        )
        values = {name: os.environ.get(name, "").strip() for name in names}
        values["APP_ORIGIN"] = os.environ.get(
            "APP_ORIGIN", os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8080")
        ).strip()
        values["LIVEKIT_AGENT_DEPLOYMENT"] = os.environ.get(
            "LIVEKIT_AGENT_DEPLOYMENT", ""
        ).strip()
        missing = [name for name in names if not values[name]]
        values["SEMANTIC_SEARCH_ENABLED"] = (
            os.environ.get("SEMANTIC_SEARCH_ENABLED", "false").strip().lower()
        )
        values["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "").strip()
        if values["SEMANTIC_SEARCH_ENABLED"] not in {"true", "false"}:
            raise ValueError("SEMANTIC_SEARCH_ENABLED must be true or false")
        if values["SEMANTIC_SEARCH_ENABLED"] == "true" and not values["GEMINI_API_KEY"]:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise ValueError("Missing configuration: " + ", ".join(missing))
        for name, schemes in (
            ("DATABASE_URL", {"postgres", "postgresql"}),
            ("SUPABASE_URL", {"https"}),
            ("LIVEKIT_URL", {"wss", "https"}),
        ):
            try:
                parsed = urlsplit(values[name])
            except ValueError:
                raise ValueError("Invalid URL: " + name) from None
            if parsed.scheme not in schemes or not parsed.hostname:
                raise ValueError("Invalid URL: " + name)
        return cls(values)

    def __getitem__(self, name: str) -> str:
        return self.values[name]
