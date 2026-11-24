"""Events from analysed letters and the portal calendar: ICS feed and daily summary."""

import datetime as dt
import hashlib
import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event as IcsEvent
from icalendar.cal import Component
from pydantic import BaseModel

from epp.models import Event, State, StoredLetter
from epp.storage import format_event

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class LetterEvent(BaseModel):
    """An event with its source: a letter/notice, or (letter_id None) the portal's Termine calendar."""

    uid: str
    letter_id: str | None = None
    letter_number: int | None = None
    letter_label: str
    letter_title: str
    url: str | None = None
    event: Event
    also_in: list[str] = []

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
    candidates: list[tuple[tuple[int, float, int], LetterEvent]] = []
    for letter in state.letters.values():
        if letter.removed or not letter.analysis:
            continue
        for e in letter.analysis.events:
            raw = f"{letter.id}|{e.date}|{e.start_time}|{e.title.lower()}"
            le = LetterEvent(
                uid=f"{hashlib.sha1(raw.encode()).hexdigest()[:20]}@epp",
                letter_id=letter.id,
                letter_number=letter.number,
                letter_label=letter.label,
                letter_title=letter.title,
                event=e,
            )
            published = (letter.published_at or letter.first_seen_at).timestamp()
            candidates.append(((len(letter.analysis.events), -published, -letter.number), le))

    out: list[LetterEvent] = []
    for _, le in sorted(candidates, key=lambda c: c[0]):
        dup = next((kept for kept in out if kept.letter_id != le.letter_id and same_event(kept.event, le.event)), None)
        if dup:
            dup.also_in.append(le.letter_label)
        else:
            out.append(le)
    return sorted(out, key=_event_order)


def _event_order(le: LetterEvent) -> tuple:
    return le.event.date, le.event.start_time or "", le.event.title


def merge_events(letter_events: list[LetterEvent], calendar_events: Iterable[LetterEvent]) -> list[LetterEvent]:
    """Adds calendar events; one that a letter already mentions is noted on the letter's event instead."""
    out = list(letter_events)
    for ce in calendar_events:
        dup = next((le for le in out if le.letter_id and same_event(le.event, ce.event)), None)
        if dup:
            dup.also_in.append(ce.letter_label)
        else:
            out.append(ce)
    return sorted(out, key=_event_order)


def events_between(events: list[LetterEvent], start: dt.date, end: dt.date) -> list[LetterEvent]:
    return [le for le in events if le.event.date <= end and le.last_day >= start]


def _parse_time(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def build_ics(state: State, tz: ZoneInfo, letter_url: str | None = None,
              extra: Iterable[Component] = ()) -> bytes:
    """extra: ready-made components (e.g. the portal's own calendar) appended as they are."""
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
        source = "Elternbrief" if letter.kind == "letter" else "Schwarzes Brett"
        desc = [e.details or "", f"{source} {le.letter_label}: {le.letter_title}"]
        if letter.analysis and letter.analysis.summary:
            desc += ["", letter.analysis.summary]
        if letter_url:
            link = letter_url.format(id=le.letter_id)
            desc += ["", link]
            ev.add("url", link)
        ev.add("description", "\n".join(desc).strip())
        cal.add_component(ev)
    for comp in extra:
        cal.add_component(comp)
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
    next_label: str
    next_start: dt.date
    next_end: dt.date
    next: list[DailyDay]


def daily_window(today: dt.date) -> tuple[dt.date, bool, dt.date]:
    """Returns (focus day, focus is a weekend-shifted Monday, last day of that week)."""
    shifted = today.weekday() >= 5
    focus = today + dt.timedelta(days=7 - today.weekday()) if shifted else today
    week_end = focus + dt.timedelta(days=6 - focus.weekday())
    return focus, shifted, week_end


def _day(date: dt.date, events: list[LetterEvent]) -> DailyDay:
    return DailyDay(date=date, weekday=_WEEKDAYS[date.weekday()], events=events_between(events, date, date))


def _days(start: dt.date, end: dt.date, events: list[LetterEvent]) -> list[DailyDay]:
    return [_day(start + dt.timedelta(days=i), events) for i in range((end - start).days + 1)]


def daily_summary(events: list[LetterEvent], today: dt.date, tz: ZoneInfo) -> DailySummary:
    """Today, the rest of this week and next week; on weekends shifted to Monday, its week and the week after."""
    focus, shifted, week_end = daily_window(today)
    rest_days = _days(focus + dt.timedelta(days=1), week_end, events)
    next_start, next_end = week_end + dt.timedelta(days=1), week_end + dt.timedelta(days=7)
    return DailySummary(
        generated_at=dt.datetime.now(tz),
        focus_label="Monday" if shifted else "Today",
        focus=_day(focus, events),
        rest_label="Coming week" if shifted else "This week",
        rest_start=rest_days[0].date if rest_days else None,
        rest_end=week_end if rest_days else None,
        rest=rest_days,
        next_label="Week after" if shifted else "Next week",
        next_start=next_start,
        next_end=next_end,
        next=_days(next_start, next_end, events),
    )


def daily_markdown(summary: DailySummary) -> str:
    def entries(day: DailyDay) -> list[str]:
        def source(le: LetterEvent) -> str:
            return ", ".join([le.letter_label, *le.also_in])

        return [f"- {format_event(le.event)} _({source(le)})_" for le in day.events]

    def week(label: str, days: list[DailyDay], start: dt.date | None, end: dt.date | None) -> list[str]:
        span = f" ({start:%d.%m.} – {end:%d.%m.%Y})" if start and end else ""
        out = ["", f"## {label}{span}", ""]
        busy = [d for d in days if d.events]
        for day in busy:
            out += [f"### {day.weekday}, {day.date:%d.%m.%Y}", "", *entries(day), ""]
        return out + ([] if busy else ["_No appointments_"])

    f = summary.focus
    lines = ["# Daily summary", "", f"## {summary.focus_label} – {f.weekday}, {f.date:%d.%m.%Y}", ""]
    lines += entries(f) or ["_No appointments_"]
    lines += week(summary.rest_label, summary.rest, summary.rest_start, summary.rest_end)
    lines += week(summary.next_label, summary.next, summary.next_start, summary.next_end)
    return "\n".join(lines).rstrip() + "\n"
