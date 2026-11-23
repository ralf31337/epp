"""Events from analysed letters: ICS feed and daily summary."""

import datetime as dt
import hashlib
import re
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event as IcsEvent
from pydantic import BaseModel

from epp.models import Event, State, StoredLetter
from epp.storage import format_event

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class LetterEvent(BaseModel):
    uid: str
    letter_id: str
    letter_number: int
    letter_title: str
    event: Event
    also_in: list[int] = []

    @property
    def last_day(self) -> dt.date:
        return self.event.end_date or self.event.date


_UMLAUTS = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def _title_words(title: str) -> list[str]:
    return [w for w in re.split(r"[^a-z]+", title.lower().translate(_UMLAUTS)) if len(w) >= 6]


def same_event(a: Event, b: Event) -> bool:
    """Heuristic for the same appointment mentioned in two letters (e.g. a reminder and an invitation)."""
    if a.date != b.date or a.start_time != b.start_time or (a.end_date or a.date) != (b.end_date or b.date):
        return False
    return any(
        SequenceMatcher(None, wa, wb).ratio() >= 0.8 for wa in _title_words(a.title) for wb in _title_words(b.title)
    )


def collect_events(state: State) -> list[LetterEvent]:
    """All events, with duplicates across letters merged into the most specific letter (fewest events)."""
    candidates: list[tuple[int, LetterEvent]] = []
    for letter in state.letters.values():
        if letter.removed or not letter.analysis:
            continue
        for e in letter.analysis.events:
            raw = f"{letter.id}|{e.date}|{e.start_time}|{e.title.lower()}"
            le = LetterEvent(
                uid=f"{hashlib.sha1(raw.encode()).hexdigest()[:20]}@epp",
                letter_id=letter.id,
                letter_number=letter.number,
                letter_title=letter.title,
                event=e,
            )
            candidates.append((len(letter.analysis.events), le))

    out: list[LetterEvent] = []
    for _, le in sorted(candidates, key=lambda c: (c[0], -c[1].letter_number)):
        dup = next((kept for kept in out if kept.letter_id != le.letter_id and same_event(kept.event, le.event)), None)
        if dup:
            dup.also_in.append(le.letter_number)
        else:
            out.append(le)
    return sorted(out, key=lambda le: (le.event.date, le.event.start_time or "", le.event.title))


def events_between(events: list[LetterEvent], start: dt.date, end: dt.date) -> list[LetterEvent]:
    return [le for le in events if le.event.date <= end and le.last_day >= start]


def _parse_time(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def build_ics(state: State, tz: ZoneInfo, letter_url: str | None = None) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//epp//Eltern-Portal Parser//DE")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "Eltern-Portal")
    cal.add("x-wr-timezone", str(tz))
    letters: dict[str, StoredLetter] = state.letters
    stamp = dt.datetime.now(dt.timezone.utc)

    for le in collect_events(state):
        e = le.event
        ev = IcsEvent()
        ev.add("uid", le.uid)
        ev.add("dtstamp", stamp)
        ev.add("summary", e.title)
        if e.start_time:
            start = dt.datetime.combine(e.date, _parse_time(e.start_time), tz)
            if e.end_time:
                end = dt.datetime.combine(e.end_date or e.date, _parse_time(e.end_time), tz)
                if end <= start:
                    end = start + dt.timedelta(hours=1)
            else:
                end = start + dt.timedelta(hours=1)
            ev.add("dtstart", start.astimezone(dt.timezone.utc))
            ev.add("dtend", end.astimezone(dt.timezone.utc))
        else:
            ev.add("dtstart", e.date)
            ev.add("dtend", (e.end_date or e.date) + dt.timedelta(days=1))
        if e.location:
            ev.add("location", e.location)

        letter = letters[le.letter_id]
        desc = [e.details or "", f"Elternbrief #{le.letter_number}: {le.letter_title}"]
        if letter.analysis and letter.analysis.summary:
            desc += ["", letter.analysis.summary]
        if letter_url:
            link = letter_url.format(id=le.letter_id)
            desc += ["", link]
            ev.add("url", link)
        ev.add("description", "\n".join(desc).strip())
        cal.add_component(ev)
    return cal.to_ical()


class DailyDay(BaseModel):
    date: dt.date
    weekday: str
    events: list[LetterEvent]


class DailySummary(BaseModel):
    generated_at: dt.datetime
    focus_label: str
    focus: DailyDay
    rest_label: str
    rest_start: dt.date | None
    rest_end: dt.date | None
    rest: list[DailyDay]


def daily_window(today: dt.date) -> tuple[dt.date, bool, dt.date]:
    """Returns (focus day, focus is a weekend-shifted Monday, last day of that week)."""
    shifted = today.weekday() >= 5
    focus = today + dt.timedelta(days=7 - today.weekday()) if shifted else today
    week_end = focus + dt.timedelta(days=6 - focus.weekday())
    return focus, shifted, week_end


def _day(date: dt.date, events: list[LetterEvent]) -> DailyDay:
    return DailyDay(date=date, weekday=_WEEKDAYS[date.weekday()], events=events_between(events, date, date))


def daily_summary(state: State, today: dt.date, tz: ZoneInfo) -> DailySummary:
    events = collect_events(state)
    focus, shifted, week_end = daily_window(today)
    rest_days = []
    d = focus + dt.timedelta(days=1)
    while d <= week_end:
        rest_days.append(_day(d, events))
        d += dt.timedelta(days=1)
    return DailySummary(
        generated_at=dt.datetime.now(tz),
        focus_label="Monday" if shifted else "Today",
        focus=_day(focus, events),
        rest_label="Coming week" if shifted else "Rest of the week",
        rest_start=rest_days[0].date if rest_days else None,
        rest_end=week_end if rest_days else None,
        rest=rest_days,
    )


def daily_markdown(summary: DailySummary) -> str:
    def entries(day: DailyDay) -> list[str]:
        def source(le: LetterEvent) -> str:
            return ", ".join(f"#{n}" for n in [le.letter_number, *le.also_in])

        return [f"- {format_event(le.event)} _(letter {source(le)})_" for le in day.events]

    f = summary.focus
    lines = ["# Daily summary", "", f"## {summary.focus_label} – {f.weekday}, {f.date:%d.%m.%Y}", ""]
    lines += entries(f) or ["_No appointments_"]
    lines += ["", f"## {summary.rest_label}", ""]
    any_rest = False
    for day in summary.rest:
        if day.events:
            any_rest = True
            lines += [f"### {day.weekday}, {day.date:%d.%m.%Y}", "", *entries(day), ""]
    if not any_rest:
        lines.append("_No appointments_")
    return "\n".join(lines).rstrip() + "\n"
