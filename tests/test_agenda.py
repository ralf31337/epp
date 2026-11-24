import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from epp.agenda import build_ics, collect_events, daily_markdown, daily_summary, daily_window, merge_events
from epp.analysis import parse_events, time_in_text
from epp.appconfig import DEFAULT_CRON, next_runs, validate_cron
from epp.models import Analysis, Event, State, StoredLetter
from epp.portal_calendar import SOURCE_NOTE, _details, annotate, to_events

TZ = ZoneInfo("Europe/Berlin")


def _letter(events: list[Event]) -> StoredLetter:
    now = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    return StoredLetter(
        id="1", number=1, title="Brief", published_at=now, classes=[], acknowledged=True,
        description_md="", description_sha256="x", attachments=[], first_seen_at=now, updated_at=now,
        analysis=Analysis(summary="S", events=events, model="m", input_key="k", analyzed_at=now),
    )


@pytest.mark.parametrize(
    ("today", "focus", "shifted", "week_end"),
    [
        ("2026-11-23", "2026-11-23", False, "2026-11-29"),  # Monday
        ("2026-11-27", "2026-11-27", False, "2026-11-29"),  # Friday
        ("2026-11-28", "2026-11-30", True, "2026-12-06"),  # Saturday -> next Monday
        ("2026-11-29", "2026-11-30", True, "2026-12-06"),  # Sunday -> next Monday
    ],
)
def test_daily_window(today, focus, shifted, week_end):
    assert daily_window(dt.date.fromisoformat(today)) == (
        dt.date.fromisoformat(focus), shifted, dt.date.fromisoformat(week_end)
    )


def test_daily_summary_sections():
    state = State(letters={"1": _letter([
        Event(title="Heute", date=dt.date(2026, 11, 30), start_time="19:00"),
        Event(title="Später", date=dt.date(2026, 12, 2)),
        Event(title="Danach", date=dt.date(2026, 12, 8)),
        Event(title="Viel später", date=dt.date(2026, 12, 14)),
        Event(title="Mehrtägig", date=dt.date(2026, 11, 29), end_date=dt.date(2026, 12, 1)),
    ])})
    s = daily_summary(collect_events(state), dt.date(2026, 11, 28), TZ)
    assert s.focus_label == "Monday"
    assert [le.event.title for le in s.focus.events] == ["Mehrtägig", "Heute"]
    rest = {d.date.isoformat(): [le.event.title for le in d.events] for d in s.rest}
    assert rest["2026-12-01"] == ["Mehrtägig"]
    assert rest["2026-12-02"] == ["Später"]
    assert "Danach" not in str(rest)
    assert (s.next_label, s.next_start, s.next_end) == ("Week after", dt.date(2026, 12, 7), dt.date(2026, 12, 13))
    assert [(d.date.day, le.event.title) for d in s.next for le in d.events] == [(8, "Danach")]

    weekday = daily_summary(collect_events(state), dt.date(2026, 11, 25), TZ)
    assert (weekday.focus_label, weekday.rest_label, weekday.next_label) == ("Today", "This week", "Next week")
    assert (weekday.next_start, weekday.next_end) == (dt.date(2026, 11, 30), dt.date(2026, 12, 6))
    md = daily_markdown(weekday)
    assert "## This week (26.11. – 29.11.2026)" in md
    assert "## Next week (30.11. – 06.12.2026)" in md


def test_cron_validation():
    assert validate_cron(" 30  6,18 * * * ") == DEFAULT_CRON
    for bad in ["", "* * *", "61 * * * *", "every day", "* * * * * *"]:
        with pytest.raises(ValueError):
            validate_cron(bad)
    runs = next_runs(DEFAULT_CRON, TZ, 2, dt.datetime(2026, 11, 23, 7, 0, tzinfo=TZ))
    assert [r.strftime("%d %H:%M") for r in runs] == ["23 18:30", "24 06:30"]


def test_parse_events_cleans_llm_output():
    events = parse_events([
        {"title": "Elternabend", "date": "2026-09-28", "start_time": "19:00", "end_time": "21:00"},
        {"title": "Elternabend", "date": "2026-09-28", "start_time": "19:00"},
        {"title": "Kaputt", "date": "28.09."},
        {"title": "", "date": "2026-09-28"},
        {"title": "Frist: Anmeldung", "date": "2026-09-20", "start_time": "noon", "end_time": "13:00",
         "end_date": "2026-09-19"},
    ])
    assert [(e.title, e.start_time, e.end_time, e.end_date) for e in events] == [
        ("Frist: Anmeldung", None, None, None),
        ("Elternabend", "19:00", "21:00", None),
    ]


def test_times_must_appear_in_source():
    assert time_in_text("19:00", "Beginn um 19 Uhr")
    assert time_in_text("09:30", "ab 9.30 Uhr")
    assert not time_in_text("20:00", "Beginn um 19:00 Uhr")
    events = parse_events(
        [{"title": "Konzert", "date": "2026-11-25", "start_time": "19:00", "end_time": "20:00"}],
        source_text="Konzert am 25.11. um 19:00 Uhr",
    )
    assert (events[0].start_time, events[0].end_time) == ("19:00", None)


def test_duplicates_across_letters_are_merged():
    reminder = _letter([
        Event(title="Kaleidoskop-Abend", date=dt.date(2026, 11, 25), start_time="19:00"),
        Event(title="Buchvorstellung", date=dt.date(2026, 11, 27), start_time="19:00"),
        Event(title="Weihnachtsferien", date=dt.date(2026, 12, 24), end_date=dt.date(2027, 1, 10)),
    ])
    reminder.id, reminder.number = "15", 15
    invitation = _letter([Event(title='Herbst-Kaleidoskop 2026', date=dt.date(2026, 11, 25), start_time="19:00")])
    invitation.id, invitation.number = "17", 17
    books = _letter([Event(title="Büchervorstellung", date=dt.date(2026, 11, 27), start_time="19:00")])
    books.id, books.number = "16", 16
    events = collect_events(State(letters={"15": reminder, "16": books, "17": invitation}))
    assert [(le.letter_label, le.event.title, le.also_in) for le in events] == [
        ("#17", "Herbst-Kaleidoskop 2026", ["#15"]),
        ("#16", "Büchervorstellung", ["#15"]),
        ("#15", "Weihnachtsferien", []),
    ]


def test_ics_contains_events():
    state = State(letters={"1": _letter([
        Event(title="Konzert", date=dt.date(2026, 11, 25), start_time="19:00", end_time="20:30"),
        Event(title="Ausflug", date=dt.date(2026, 12, 1), end_date=dt.date(2026, 12, 2)),
    ])})
    ics = build_ics(state, TZ, "http://x/#/letters/{id}").decode()
    assert "SUMMARY:Konzert" in ics
    assert "DTSTART:20261125T180000Z" in ics
    assert "DTSTART;VALUE=DATE:20261201" in ics
    assert "DTEND;VALUE=DATE:20261203" in ics
    assert "Elternbrief #1: Brief" in ics


PORTAL_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//portal//EN
BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:STANDARD
DTSTART:19701025T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:abc@portal
DTSTART;TZID=Europe/Berlin:20261201T080000
DTEND;TZID=Europe/Berlin:20261201T090000
SUMMARY:Schulaufgabe Mathematik
DESCRIPTION:Klasse 5D
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261223
SUMMARY:Weihnachtsferien
END:VEVENT
END:VCALENDAR
"""


def test_portal_events_are_merged_with_source():
    source = "https://tenant.eltern-portal.org/service/termine"
    ics = build_ics(State(), TZ, None, extra=annotate(PORTAL_ICS, source))
    cal = Calendar.from_ical(ics)
    events = {str(e["summary"]): e for e in cal.walk("VEVENT")}
    assert len(cal.walk("VTIMEZONE")) == 1
    exam = events["Schulaufgabe Mathematik"]
    assert str(exam["uid"]) == "portal-abc@portal"
    assert str(exam["description"]) == f"Klasse 5D\n\n{SOURCE_NOTE}\n{source}"
    assert str(exam["url"]) == source
    holidays = events["Weihnachtsferien"]
    assert str(holidays["uid"]).startswith("portal-")
    assert str(holidays["description"]) == f"{SOURCE_NOTE}\n{source}"


MULTI_DAY_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:trip
DTSTART:20261207T230000Z
DTEND:20261210T230000Z
SUMMARY:Skilager
END:VEVENT
BEGIN:VEVENT
UID:break
DTSTART;VALUE=DATE:20261223
DTEND;VALUE=DATE:20270109
SUMMARY:Weihnachtsferien
END:VEVENT
END:VCALENDAR
"""


def test_portal_feed_as_daily_events():
    source = "https://tenant.eltern-portal.org/service/termine"
    exam, holidays = to_events(PORTAL_ICS, source, TZ)
    assert (exam.letter_id, exam.letter_label, exam.url) == (None, "Termine", source)
    assert (exam.event.date, exam.event.start_time, exam.event.end_time) == (dt.date(2026, 12, 1), "08:00", "09:00")
    assert exam.event.details == "Klasse 5D"
    assert (holidays.event.date, holidays.event.start_time, holidays.event.end_date) == (dt.date(2026, 12, 23), None, None)

    trip, long_break = to_events(MULTI_DAY_ICS, source, TZ)
    # Midnight local time on both ends: an all-day trip from Dec 8 to Dec 10.
    assert (trip.event.date, trip.event.start_time, trip.event.end_date) == (dt.date(2026, 12, 8), None, dt.date(2026, 12, 10))
    assert (long_break.event.date, long_break.event.end_date) == (dt.date(2026, 12, 23), dt.date(2027, 1, 8))


def test_portal_descriptions_drop_repeated_title_and_generic_calendar():
    assert _details("Sommerferien\n\nKalender: Kalender", "Sommerferien") is None
    assert _details("Mathematik\n\nKalender: Schulaufgabe", "Mathematik") == "Schulaufgabe"
    assert _details("Bitte Turnzeug mitbringen\n\nKalender: Kalender", "Wandertag") == "Bitte Turnzeug mitbringen"
    assert _details(None, "x") is None


def test_portal_events_merge_into_matching_letter_events():
    letter = _letter([Event(title="Beginn der Weihnachtsferien", date=dt.date(2026, 12, 23))])
    portal = to_events(PORTAL_ICS, "https://x/service/termine", TZ)
    merged = merge_events(collect_events(State(letters={"1": letter})), portal)
    assert [(le.letter_label, le.event.title, le.also_in) for le in merged] == [
        ("Termine", "Schulaufgabe Mathematik", []),
        ("#1", "Beginn der Weihnachtsferien", ["Termine"]),
    ]
