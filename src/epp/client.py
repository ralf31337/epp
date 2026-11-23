import re
from email.message import Message

import httpx
from bs4 import BeautifulSoup

from epp.config import Settings
from epp.credentials import Credentials

LOGIN_PATH = "/"
LOGIN_POST_PATH = "/includes/project/auth/login.php"
ELTERNBRIEFE_PATH = "/aktuelles/elternbriefe"


class PortalError(RuntimeError):
    pass


class AuthError(PortalError):
    pass


def _is_login_page(html: str) -> bool:
    return "form-signin" in html and "name='password'" in html.replace('"', "'")


def portal_base_url(settings: Settings, creds: Credentials) -> str:
    return f"https://{creds.tenant}.{settings.base_domain}"


class PortalClient:
    def __init__(self, settings: Settings, creds: Credentials):
        self.creds = creds
        self.base_url = portal_base_url(settings, creds)
        self._http = httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": "epp-parser/0.1 (+self-hosted)"},
        )

    def __enter__(self) -> "PortalClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def login(self) -> None:
        resp = self._http.get(LOGIN_PATH)
        resp.raise_for_status()
        csrf_input = BeautifulSoup(resp.text, "lxml").select_one("form.form-signin input[name=csrf]")
        if csrf_input is None or not csrf_input.get("value"):
            raise PortalError("CSRF token not found on login page")

        resp = self._http.post(
            LOGIN_POST_PATH,
            data={
                "csrf": csrf_input["value"],
                "username": self.creds.username,
                "password": self.creds.password.get_secret_value(),
                "go_to": "",
            },
        )
        resp.raise_for_status()
        if _is_login_page(resp.text):
            raise AuthError("Login failed (check username/password)")

    def get_page(self, path: str) -> str:
        resp = self._http.get(path)
        resp.raise_for_status()
        if _is_login_page(resp.text):
            raise AuthError(f"Not logged in when requesting {path}")
        return resp.text

    def get_elternbriefe_html(self) -> str:
        return self.get_page(ELTERNBRIEFE_PATH)

    def download(self, url: str) -> tuple[bytes, str | None]:
        """Returns file content and the filename from Content-Disposition (if any)."""
        resp = self._http.get(url)
        resp.raise_for_status()
        if "text/html" in resp.headers.get("content-type", ""):
            raise PortalError(f"Expected a file but got HTML from {url} (csrf token expired?)")
        return resp.content, _filename_from_disposition(resp.headers.get("content-disposition"))


def _filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    msg = Message()
    msg["content-disposition"] = value
    name = msg.get_filename()
    if name:
        return name
    m = re.search(r'filename="?([^";]+)"?', value)
    return m.group(1) if m else None
