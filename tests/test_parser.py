from pathlib import Path

from epp.parser import parse_elternbriefe, sha256_text

BASE = "https://tenant.eltern-portal.org"
HTML = (Path(__file__).parent / "fixtures" / "elternbriefe.html").read_text(encoding="utf-8")


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
