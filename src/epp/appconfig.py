"""Runtime configuration edited in the web app and persisted in the data volume."""

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, Field, HttpUrl, field_validator

from epp.storage import atomic_write

DEFAULT_CRON = "30 6,18 * * *"


def validate_cron(expr: str) -> str:
    expr = " ".join(expr.split())
    if len(expr.split(" ")) != 5 or not croniter.is_valid(expr):
        raise ValueError("invalid cron expression (expected 5 fields: minute hour day month weekday)")
    return expr


def next_runs(expr: str, tz: ZoneInfo, count: int = 3, start: datetime | None = None) -> list[datetime]:
    it = croniter(validate_cron(expr), start or datetime.now(tz))
    return [it.get_next(datetime) for _ in range(count)]


class OllamaEndpoint(BaseModel):
    enabled: bool = False
    host: str = "host.docker.internal"
    port: int = Field(11434, ge=1, le=65535)
    model: str = ""
    # PDF parsing only: "auto" uses the PDF text layer where present and vision for scanned pages/images.
    mode: Literal["auto", "always"] = "auto"

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @property
    def base_url(self) -> str:
        if self.host.startswith(("http://", "https://")):
            return f"{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.host) and bool(self.model)


class AppConfig(BaseModel):
    schedule_cron: str = DEFAULT_CRON
    webhook_url: HttpUrl | None = None
    pdf_ollama: OllamaEndpoint = OllamaEndpoint()
    context_ollama: OllamaEndpoint = OllamaEndpoint()
    ics_token: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("schedule_cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        return validate_cron(v)


class AppConfigUpdate(BaseModel):
    schedule_cron: str
    webhook_url: HttpUrl | None = None
    pdf_ollama: OllamaEndpoint
    context_ollama: OllamaEndpoint

    @field_validator("schedule_cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        return validate_cron(v)

    @field_validator("webhook_url", mode="before")
    @classmethod
    def _empty_webhook(cls, v):
        return None if v in ("", None) else v


class ConfigStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "config.json"
        self._lock = threading.Lock()
        self._config = self._load()

    def _load(self) -> AppConfig:
        if self.path.exists():
            config = AppConfig.model_validate_json(self.path.read_text(encoding="utf-8"))
        else:
            config = AppConfig()
        self._save(config)
        return config

    def _save(self, config: AppConfig) -> None:
        atomic_write(self.path, config.model_dump_json(indent=2).encode("utf-8"))

    def get(self) -> AppConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def update(self, update: AppConfigUpdate) -> AppConfig:
        with self._lock:
            data = self._config.model_dump(mode="json")
            data.update(update.model_dump(mode="json"))
            self._config = AppConfig.model_validate(data)
            self._save(self._config)
            return self._config.model_copy(deep=True)
