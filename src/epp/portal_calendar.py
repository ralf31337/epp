"""School calendar from the portal's "Termine" page, merged into the ICS feed.

The ICS URL is looked up during a sync (it needs the portal session) and, like the downloaded calendar,
kept in memory only: nothing from it is written to the data directory. The feed itself is a secret URL
that works without a session, so it is refreshed on demand when the app's ICS feed is requested.
"""

import datetime as dt
import hashlib
import logging
import re
import threading
from collections.abc import Callable
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar
from icalendar.cal import Component

from epp.agenda import LetterEvent
from epp.client import PortalClient, PortalError
from epp.models import Event

log = logging.getLogger(__name__)

TERMINE_PATH = "/service/termine"
ICS_URL_PATH = "/includes/get_ics_url.php"
REFRESH_SECONDS = 15 * 60
SOURCE_LABEL = "Termine"
SOURCE_TITLE = "Schulaufgaben / Weitere Termine"
SOURCE_NOTE = f"Quelle: Eltern-Portal – {SOURCE_TITLE}"
_CSRF_RE = re.compile(r"fetch_ics_url\(\s*[\"']([^\"']+)[\"']")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _https(url: str) -> str:
    return re.sub(r"^webcals?://", "https://", url.strip(), flags=re.I)


def _download(url: str) -> bytes:
    """The portal serves the feed as text/html, so the content is checked instead of the type.
    Errors never include the URL: its token grants access to the calendar."""
    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True,
                         headers={"User-Agent": "epp-parser/0.1 (+self-hosted)"})
    except httpx.HTTPError as e:
        raise PortalError(f"Termine feed unreachable ({type(e).__name__})") from None
    if resp.status_code != 200:
        raise PortalError(f"Termine feed returned HTTP {resp.status_code}")
    if b"BEGIN:VCALENDAR" not in resp.content[:2048]:
        raise PortalError("Termine feed did not return an iCalendar file")
    return resp.content


_CALENDAR_LINE_RE = re.compile(r"^Kalender:\s*(.*)$", re.M)


def _details(description: str | None, title: str) -> str | None:
    """Drops the repeated title and the generic "Kalender: Kalender" line the portal adds."""
    if not description:
        return None
    m = _CALENDAR_LINE_RE.search(description)
    calendar = m.group(1).strip() if m else ""
    text = _CALENDAR_LINE_RE.sub("", description).strip()
    parts = [p for p in [text if text != title else "", calendar if calendar != "Kalender" else ""] if p]
    return " · ".join(parts) or None


def _uid(comp: Component) -> str:
    return "portal-" + str(comp.get("uid") or hashlib.sha1(comp.to_ical()).hexdigest()[:20])


def annotate(content: bytes, source_url: str) -> list[Component]:
    """VTIMEZONEs and VEVENTs of the portal feed, with UIDs namespaced and a source note added."""
    out: list[Component] = []
    for comp in Calendar.from_ical(content).subcomponents:
        if comp.name == "VTIMEZONE":
            out.append(comp)
        elif comp.name == "VEVENT":
            uid = _uid(comp)
            comp.pop("uid", None)
            comp.add("uid", uid)
            desc = str(comp.pop("description", "") or "").strip()
            comp.add("description", "\n\n".join(p for p in [desc, f"{SOURCE_NOTE}\n{source_url}"] if p))
            if "url" not in comp:
                comp.add("url", source_url)
            out.append(comp)
    return out


def _local(value: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)


def _text(comp: Component, key: str) -> str | None:
    return str(comp.get(key) or "").strip() or None


def to_events(content: bytes, source_url: str, tz: ZoneInfo) -> list[LetterEvent]:
    """The feed's VEVENTs as events for the daily summary and the API."""
    out: list[LetterEvent] = []
    for comp in Calendar.from_ical(content).walk("VEVENT"):
        start = comp.decoded("dtstart", None)
        if start is None:
            continue
        end = comp.decoded("dtend", None)
        end_date = start_time = end_time = None
        if isinstance(start, dt.datetime):
            start = _local(start, tz)
            date = start.date()
            if isinstance(end, dt.datetime):
                end = _local(end, tz)
                if end.date() > date:
                    # An end at midnight belongs to the previous day.
                    last = end.date() - dt.timedelta(days=1) if end.time() == dt.time() else end.date()
                    end_date = last if last > date else None
                elif end > start:
                    end_time = f"{end:%H:%M}"
            if start.time() != dt.time() or end_time:
                start_time = f"{start:%H:%M}"
        else:
            date = start
            if isinstance(end, dt.date) and end - dt.timedelta(days=1) > start:
                end_date = end - dt.timedelta(days=1)
        title = _text(comp, "summary") or "Termin"
        event = Event(
            title=title, date=date, end_date=end_date, start_time=start_time, end_time=end_time,
            location=_text(comp, "location"), details=_details(_text(comp, "description"), title),
        )
        out.append(LetterEvent(uid=_uid(comp), letter_label=SOURCE_LABEL, letter_title=SOURCE_TITLE,
                               url=source_url, event=event))
    return out


class PortalCalendar:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ics_url: str | None = None
        self._source_url: str | None = None
        self._content: bytes | None = None
        self._fetched_at: dt.datetime | None = None
        self._error: str | None = None

    def discover(self, client: PortalClient) -> None:
        """Looks up the feed URL with a logged-in client and downloads the feed once."""
        m = _CSRF_RE.search(client.get_page(TERMINE_PATH))
        if not m:
            raise PortalError("ICS URL token not found on the Termine page")
        url = _https(client.get_page(f"{ICS_URL_PATH}?csrf={m.group(1)}"))
        if not url.startswith("https://"):
            raise PortalError("Termine page returned no ICS URL")
        content = _download(url)
        with self._lock:
            self._ics_url, self._source_url = url, client.base_url + TERMINE_PATH
            self._content, self._fetched_at, self._error = content, _now(), None

    def clear(self) -> None:
        with self._lock:
            self._ics_url = self._source_url = self._content = self._fetched_at = self._error = None

    def _refresh(self) -> None:
        """Re-downloads a stale feed; on failure the previous copy is kept."""
        url = self._ics_url
        if not url or (self._fetched_at and (_now() - self._fetched_at).total_seconds() < REFRESH_SECONDS):
            return
        try:
            content = _download(url)
            with self._lock:
                self._content, self._error = content, None
        except Exception as e:
            log.warning("Refreshing the Termine feed failed: %s", e)
            with self._lock:
                self._error = str(e)
        finally:
            with self._lock:
                self._fetched_at = _now()

    def _convert(self, convert: Callable[[bytes, str], list]) -> list:
        self._refresh()
        with self._lock:
            content, source = self._content, self._source_url
        if not content or not source:
            return []
        try:
            return convert(content, source)
        except Exception as e:
            log.warning("Parsing the Termine feed failed: %s", e)
            return []

    def components(self) -> list[Component]:
        return self._convert(annotate)

    def events(self, tz: ZoneInfo) -> list[LetterEvent]:
        return self._convert(lambda content, source: to_events(content, source, tz))

    def status(self) -> dict:
        with self._lock:
            return {
                "available": self._content is not None,
                "events": self._content.count(b"BEGIN:VEVENT") if self._content else 0,
                "fetched_at": self._fetched_at,
                "error": self._error,
            }


portal_calendar = PortalCalendar()
