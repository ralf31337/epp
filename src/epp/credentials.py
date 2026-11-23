"""Portal credentials live only in process memory, so a restart requires entering them again."""

import re
import threading

from pydantic import BaseModel, SecretStr, field_validator

_TENANT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class Credentials(BaseModel):
    tenant: str
    username: str
    password: SecretStr

    @field_validator("tenant")
    @classmethod
    def _tenant(cls, v: str) -> str:
        v = v.strip().lower()
        if not _TENANT_RE.match(v):
            raise ValueError("tenant must be the sub-domain only, e.g. 'myschool'")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username is required")
        return v


class CredentialStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._creds: Credentials | None = None

    def get(self) -> Credentials | None:
        with self._lock:
            return self._creds

    def set(self, creds: Credentials) -> None:
        with self._lock:
            self._creds = creds

    def clear(self) -> None:
        with self._lock:
            self._creds = None


credential_store = CredentialStore()
