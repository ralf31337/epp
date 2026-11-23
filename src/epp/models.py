import datetime as dt

from pydantic import BaseModel


class ParsedAttachment(BaseModel):
    repo: str
    name: str
    url: str


class ParsedLetter(BaseModel):
    id: str
    number: int
    title: str
    published_at: dt.datetime | None
    classes: list[str]
    acknowledged: bool
    description_md: str
    description_sha256: str
    attachments: list[ParsedAttachment]


class StoredAttachment(BaseModel):
    repo: str
    name: str
    file: str
    size: int
    sha256: str
    text_file: str | None = None
    text_method: str | None = None
    text_key: str | None = None
    text_error: str | None = None


class Event(BaseModel):
    title: str
    date: dt.date
    end_date: dt.date | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    details: str | None = None


class Analysis(BaseModel):
    summary: str
    key_facts: list[str] = []
    events: list[Event] = []
    model: str
    input_key: str
    analyzed_at: dt.datetime


class StoredLetter(BaseModel):
    id: str
    number: int
    title: str
    published_at: dt.datetime | None
    classes: list[str]
    acknowledged: bool
    description_md: str
    description_sha256: str
    attachments: list[StoredAttachment]
    first_seen_at: dt.datetime
    updated_at: dt.datetime
    removed: bool = False
    analysis: Analysis | None = None
    analysis_error: str | None = None
    webhook_pending: bool = False


class State(BaseModel):
    last_sync_at: dt.datetime | None = None
    letters: dict[str, StoredLetter] = {}


class SyncResult(BaseModel):
    started_at: dt.datetime
    finished_at: dt.datetime
    new: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    removed: list[str] = []
    downloaded_files: int = 0
    extracted_files: int = 0
    analyzed_letters: int = 0
    webhooks_sent: int = 0
    errors: list[str] = []
