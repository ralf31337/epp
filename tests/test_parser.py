import datetime as dt
from pathlib import Path

from epp.models import State, StoredLetter
from epp.parser import parse_elternbriefe, parse_schwarzes_brett, sha256_text
from epp.sync import _number_notices

BASE = "https://tenant.eltern-portal.org"
FIXTURES = Path(__file__).parent / "fixtures"
HTML = (FIXTURES / "elternbriefe.html").read_text(encoding="utf-8")
BRETT = (FIXTURES / "schwarzes_brett.html").read_text(encoding="utf-8")


def test_parses_all_letters_in_order():
    letters = parse_elternbriefe(HTML, BASE)
    assert [(l.number, l.id) for l in letters] == [(3, "103"), (2, "102"), (1, "101")]


def test_multiple_attachments_deduped_against_title_link():
    letter = parse_elternbriefe(HTML, BASE)[0]
    assert letter.title == "Einladung zum Chor"
    assert [(a.repo, a.name) for a in letter.attachments] == [
        ("501", "Chor Dienstag.pdf"),
        ("502", "Chor Donnerstag.pdf"),
    ]
    assert letter.attachments[0].url == f"{BASE}/aktuelles/get_file/?repo=501&csrf=bbb"
    assert letter.classes == ["5D", "5E"]
    assert letter.published_at.isoformat() == "2026-09-15T10:29:00+02:00"
    assert letter.description_md == "Liebe Eltern,\n\nanbei **zwei** Einladungen."
    assert letter.description_sha256 == sha256_text(letter.description_md)


def test_letter_without_attachment():
    letter = parse_elternbriefe(HTML, BASE)[1]
    assert letter.title == "Streptokokken Infektion"
    assert letter.attachments == []
    assert letter.acknowledged is True
    assert letter.description_md == "Liebe Eltern,\\\nbitte aufmerksam sein."


def test_unacknowledged_letter():
    letter = parse_elternbriefe(HTML, BASE)[2]
    assert letter.acknowledged is False
    assert len(letter.attachments) == 1


def test_schwarzes_brett_current_and_archive():
    notices = parse_schwarzes_brett(BRETT, BASE)
    assert [n.title for n in notices] == [
        "Bitte um pünktliches Erscheinen", "Stellenausschreibung Sekretariat",
        "Bitte im Zahlungssystem anmelden", "Kurzstunden", "Kurzstunden",
    ]
    assert all(n.kind == "notice" and n.id.startswith("sb-") for n in notices)
    assert len({n.id for n in notices}) == 5

    current, job, archived, *_ = notices
    assert current.published_at.isoformat() == "2026-11-16T00:00:00+01:00"
    assert current.description_md == "Sehr geehrte Eltern,\n\nbitte pünktlich sein.\n\nIhre Schulleitung"
    assert job.published_at.isoformat() == "2026-10-26T08:15:00+01:00"
    assert job.description_md == ""
    assert [(a.repo, a.name, a.url) for a in job.attachments] == [
        ("35056", "Stellenausschreibung.pdf", f"{BASE}/aktuelles/get_file/?repo=35056&csrf=aaa")
    ]
    assert archived.published_at.date() == dt.date(2026, 10, 29)
    assert archived.description_md == "Liebe Eltern,\n\ndie **Frist läuft morgen ab.**"
    assert [a.name for a in archived.attachments] == ["Anmeldeprozess.pdf"]
    assert notices[3].description_md == "Bitte beachten:\n\n- Unterricht endet um 12:00 Uhr."
    assert notices[4].description_md == "Liebe Eltern,\n\nZeile zwei."


def test_notice_ids_are_stable_between_current_and_archive():
    # The id only depends on the day and title, not on the time or on where the notice is shown.
    current = parse_schwarzes_brett(BRETT, BASE)[0]
    archived_html = BRETT.replace("eingestellt am 16.11.2026 00:00:00", "eingestellt am 16.11.2026 09:30:00")
    assert parse_schwarzes_brett(archived_html, BASE)[0].id == current.id


def test_notice_numbers_count_up_from_oldest_and_stay():
    notices = parse_schwarzes_brett(BRETT, BASE)
    state = State()
    _number_notices(state, notices)
    # Oldest first by date, not by position: a current notice can be older than an archived one.
    # The two "Kurzstunden" share a day and keep their page order (the lower one is older).
    assert [(n.title, n.number) for n in notices] == [
        ("Bitte um pünktliches Erscheinen", 5), ("Stellenausschreibung Sekretariat", 3),
        ("Bitte im Zahlungssystem anmelden", 4), ("Kurzstunden", 2), ("Kurzstunden", 1),
    ]

    now = dt.datetime(2026, 11, 24, tzinfo=dt.timezone.utc)
    for n in notices[1:]:  # the newest one is gone (e.g. deleted), its number must not be reused
        state.letters[n.id] = StoredLetter(**n.model_dump(exclude={"attachments"}), attachments=[],
                                           first_seen_at=now, updated_at=now)
    state.letters["sb-gone"] = StoredLetter(**notices[0].model_dump(exclude={"attachments", "id"}), id="sb-gone",
                                            attachments=[], first_seen_at=now, updated_at=now, removed=True)
    again = parse_schwarzes_brett(BRETT, BASE)
    _number_notices(state, again)
    assert [n.number for n in again] == [6, 3, 4, 2, 1]
    assert state.letters[again[1].id].label == "~3"
