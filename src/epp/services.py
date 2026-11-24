import datetime as dt

from epp import urls
from epp.agenda import DailySummary, LetterEvent, collect_events, daily_summary, merge_events
from epp.appconfig import ConfigStore
from epp.config import Settings
from epp.credentials import credential_store
from epp.models import StoredLetter, newest_first
from epp.portal_calendar import portal_calendar
from epp.scheduler import Scheduler
from epp.storage import Storage
from epp.sync import Runner

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
urls.configure(settings.public_url)
storage = Storage(settings.data_dir)
config_store = ConfigStore(settings.data_dir)
runner = Runner(settings, storage, config_store, credential_store)
scheduler = Scheduler(settings, config_store, runner)


def today() -> dt.date:
    return dt.datetime.now(settings.tz).date()


def letters(include_removed: bool = False) -> list[StoredLetter]:
    return newest_first(l for l in storage.load_state().letters.values() if include_removed or not l.removed)


def search_letters(query: str) -> list[StoredLetter]:
    terms = [t for t in query.lower().split() if t]
    out = []
    for letter in letters():
        haystack = " ".join(
            [letter.title, letter.description_md]
            + ([letter.analysis.summary, *letter.analysis.key_facts] if letter.analysis else [])
            + [storage.attachment_text(letter.id, a) for a in letter.attachments]
        ).lower()
        if all(t in haystack for t in terms):
            out.append(letter)
    return out


def events() -> list[LetterEvent]:
    """Events from letters and notices plus the portal's Termine calendar."""
    return merge_events(collect_events(storage.load_state()), portal_calendar.events(settings.tz))


def daily(date: dt.date | None = None) -> DailySummary:
    return daily_summary(events(), date or today(), settings.tz)


def status() -> dict:
    creds = credential_store.get()
    cfg = config_store.get()
    state = storage.load_state()
    return {
        "credentials": {"configured": creds is not None, "tenant": creds.tenant if creds else None,
                        "username": creds.username if creds else None},
        "job": runner.status.model_dump(mode="json"),
        "last_sync_at": state.last_sync_at,
        "letters": sum(1 for l in state.letters.values() if not l.removed and l.kind == "letter"),
        "notices": sum(1 for l in state.letters.values() if not l.removed and l.kind == "notice"),
        "portal_calendar": portal_calendar.status(),
        "analysed": sum(1 for l in state.letters.values() if not l.removed and l.analysis),
        "schedule_cron": cfg.schedule_cron,
        "next_run": scheduler.next_run,
        "scheduler_note": scheduler.last_skip_reason,
        "pdf_ollama": cfg.pdf_ollama.active,
        "context_ollama": cfg.context_ollama.active,
        "public_url": urls.base_url(),
    }
