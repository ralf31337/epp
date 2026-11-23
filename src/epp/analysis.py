"""LLM step: summary, key facts and dated events for one letter."""

import datetime as dt
import hashlib
import re
from zoneinfo import ZoneInfo

from epp import ollama
from epp.appconfig import OllamaEndpoint
from epp.models import Analysis, Event, StoredLetter

PROMPT_VERSION = "4"
MAX_INPUT_CHARS = 40_000
_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

SYSTEM = (
    "You analyse letters from a German school to parents. Always write summary, key_facts, event titles "
    "and details in German. Be factual and concise; never invent information."
)

# Ollama does not strictly enforce JSON schemas (models may invent keys and loop), so plain JSON
# mode plus an explicit example works more reliably; the result is validated in parse_events.
RESPONSE_EXAMPLE = (
    '{"summary": "...", "key_facts": ["...", "..."], "events": [{"title": "...", "date": "YYYY-MM-DD", '
    '"end_date": null, "start_time": "HH:MM or null", "end_time": null, "location": null, "details": null}]}'
)


def input_key(letter: StoredLetter, endpoint: OllamaEndpoint) -> str:
    parts = [PROMPT_VERSION, endpoint.model, letter.title, letter.description_sha256]
    parts += [a.text_key or a.sha256 for a in letter.attachments]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def build_prompt(letter: StoredLetter, attachment_texts: list[tuple[str, str]], tz: ZoneInfo) -> str:
    published = letter.published_at.astimezone(tz) if letter.published_at else None
    pub = f"{_WEEKDAYS[published.weekday()]}, {published:%Y-%m-%d %H:%M}" if published else "unbekannt"
    body = [f"Titel: {letter.title}", f"Veröffentlicht: {pub}", f"Klasse/n: {', '.join(letter.classes) or '-'}", "",
            "Text:", letter.description_md or "(leer)"]
    for name, text in attachment_texts:
        if text.strip():
            body += ["", f"Anhang «{name}»:", text]
    content = "\n".join(body)[:MAX_INPUT_CHARS]
    return (
        "Analyse the following school letter including its attachments. Answer in German.\n"
        "1. summary: 2-4 sentences with the essential message for parents.\n"
        "2. key_facts: the most essential facts as short bullet points (what parents must know or do, "
        "costs, deadlines, things to bring, contacts).\n"
        "3. events: every concrete date on or after the publication date (events, parent evenings, deadlines, "
        "payment or return dates, holidays, days without lessons).\n"
        "   - List every event of a series separately (e.g. each date of a series of online parent evenings).\n"
        "   - Resolve relative dates and missing years using the publication date.\n"
        "   - Periods spanning several days (e.g. Ferien, Klassenfahrt): date = first day, end_date = last day.\n"
        "   - start_time/end_time in 24h HH:MM, only if that exact time is stated for this event. "
        "Never copy times from other events and never guess an end_time.\n"
        "   - Do not list the publication date of the letter itself or dates before it.\n"
        "   - For deadlines, start the title with 'Frist:'.\n\n"
        f"{content}\n\n"
        f"Respond with exactly this JSON structure and no other keys:\n{RESPONSE_EXAMPLE}"
    )


def _clean_time(value) -> str | None:
    if not isinstance(value, str):
        return None
    m = _TIME_RE.match(value.strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _clean_date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _clean_str(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def time_in_text(hhmm: str, text: str) -> bool:
    """Whether a time like "19:00" appears in the source in a common German notation."""
    h, m = hhmm.split(":")
    hours = {h, str(int(h))}
    pattern = "|".join(
        [rf"\b{x}[:.]{m}\b" for x in hours] + ([rf"\b{x}\s*Uhr\b" for x in hours] if m == "00" else [])
    )
    return re.search(pattern, text) is not None


def parse_events(raw: list, source_text: str | None = None) -> list[Event]:
    events: list[Event] = []
    seen: set[tuple] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        title = _clean_str(item.get("title"))
        date = _clean_date(item.get("date"))
        if not title or not date:
            continue
        end_date = _clean_date(item.get("end_date"))
        if end_date and end_date <= date:
            end_date = None
        start_time = _clean_time(item.get("start_time"))
        if start_time and source_text is not None and not time_in_text(start_time, source_text):
            start_time = None
        end_time = _clean_time(item.get("end_time")) if start_time else None
        if end_time and source_text is not None and not time_in_text(end_time, source_text):
            end_time = None
        key = (title.lower(), date, start_time)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            Event(
                title=title, date=date, end_date=end_date, start_time=start_time, end_time=end_time,
                location=_clean_str(item.get("location")), details=_clean_str(item.get("details")),
            )
        )
    return sorted(events, key=lambda e: (e.date, e.start_time or ""))


def analyze(
    letter: StoredLetter, attachment_texts: list[tuple[str, str]], endpoint: OllamaEndpoint, tz: ZoneInfo
) -> Analysis:
    prompt = build_prompt(letter, attachment_texts, tz)
    data = ollama.chat_json(endpoint, prompt, "json", system=SYSTEM, think=False)
    if not isinstance(data, dict):
        raise ollama.OllamaError("Model returned JSON that is not an object")
    facts = [
        line.strip().lstrip("-•* ").strip()
        for f in data.get("key_facts") or []
        if isinstance(f, str)
        for line in f.splitlines()
    ]
    facts = [f for f in facts if f]
    return Analysis(
        summary=(data.get("summary") or "").strip(),
        key_facts=facts,
        events=parse_events(data.get("events"), source_text=prompt),
        model=endpoint.model,
        input_key=input_key(letter, endpoint),
        analyzed_at=dt.datetime.now(dt.timezone.utc),
    )
