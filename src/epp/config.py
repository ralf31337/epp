from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Deployment settings from the environment. Portal credentials are deliberately not here."""

    model_config = SettingsConfigDict(env_prefix="EPP_", extra="ignore")

    data_dir: Path = Path("/data")
    static_dir: Path | None = None
    timezone: str = "Europe/Berlin"
    base_domain: str = "eltern-portal.org"
    # Public URL when served behind a reverse proxy, e.g. "https://example.org/epp". Optional:
    # without it the URL is derived from the Forwarded / X-Forwarded-* request headers.
    public_url: str | None = None
    request_timeout_seconds: float = 30.0

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
