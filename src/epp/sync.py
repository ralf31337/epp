import datetime as dt
import hashlib
import logging
import threading

from pydantic import BaseModel

from epp import analysis, extract, urls, webhook
from epp.appconfig import AppConfig, ConfigStore
from epp.client import PortalClient
from epp.config import Settings
from epp.credentials import CredentialStore, Credentials
from epp.models import ParsedLetter, State, StoredAttachment, StoredLetter, SyncResult
from epp.parser import parse_elternbriefe
from epp.storage import Storage, atomic_write, safe_filename

log = logging.getLogger(__name__)


class JobStatus(BaseModel):
    running: bool = False
    kind: str | None = None
    phase: str | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    last_result: SyncResult | None = None
    last_error: str | None = None


class JobBusy(RuntimeError):
    pass


class MissingCredentials(RuntimeError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _needs_download(parsed: ParsedLetter, prev: StoredLetter | None) -> bool:
    if prev is None or prev.description_sha256 != parsed.description_sha256:
        return True
    return [a.repo for a in prev.attachments] != [a.repo for a in parsed.attachments]


def _unique_name(name: str, repo: str, used: set[str]) -> str:
    file = safe_filename(name, f"{repo}.pdf")
    if file in used or file == "letter.md" or file.endswith(".md"):
        file = f"{repo}_{file}"
    used.add(file)
    return file


class Runner:
    def __init__(self, settings: Settings, storage: Storage, config: ConfigStore, credentials: CredentialStore):
        self.settings = settings
        self.storage = storage
        self.config = config
        self.credentials = credentials
        self.status = JobStatus()
        self._lock = threading.Lock()

    # Job control

    def start(self, kind: str, letter_ids: list[str] | None = None) -> None:
        """Starts a job in a background thread."""
        if kind == "sync" and self.credentials.get() is None:
            raise MissingCredentials("Portal credentials are not set")
        self._claim(kind)
        threading.Thread(target=self._run, args=(kind, letter_ids), daemon=True, name=f"epp-{kind}").start()

    def run_blocking(self, kind: str, letter_ids: list[str] | None = None) -> SyncResult:
        self._claim(kind)
        return self._run(kind, letter_ids, raise_errors=True)

    def _claim(self, kind: str) -> None:
        with self._lock:
            if self.status.running:
                raise JobBusy(f"A {self.status.kind} job is already running")
            self.status = self.status.model_copy(
                update={"running": True, "kind": kind, "phase": "starting", "started_at": _now(), "finished_at": None}
            )

    def _phase(self, text: str) -> None:
        self.status.phase = text
        log.info(text)

    def _run(self, kind: str, letter_ids: list[str] | None, raise_errors: bool = False) -> SyncResult | None:
        result = SyncResult(started_at=_now(), finished_at=_now())
        error = None
        try:
            cfg = self.config.get()
            state = self.storage.load_state()
            initial_import = not state.letters
            if kind == "sync":
                creds = self.credentials.get()
                if creds is None:
                    raise MissingCredentials("Portal credentials are not set")
                self._fetch(state, creds, result)
                if not initial_import:
                    for letter_id in result.new:
                        state.letters[letter_id].webhook_pending = True
                    self.storage.save_state(state)
            force = set(letter_ids or []) if kind == "reprocess" else set()
            self._process(state, cfg, result, only=force or None, force=bool(force))
            self.storage.write_combined_md(state)
            if kind == "sync":
                self._notify(state, cfg, result)
        except Exception as e:
            error = str(e)
            log.exception("%s job failed", kind)
            if raise_errors:
                raise
        finally:
            result.finished_at = _now()
            with self._lock:
                self.status = self.status.model_copy(
                    update={"running": False, "phase": None, "finished_at": result.finished_at,
                            "last_result": result, "last_error": error}
                )
        return result

    # Pipeline steps

    def _fetch(self, state: State, creds: Credentials, result: SyncResult) -> None:
        now = _now()
        self._phase("Logging in to the portal")
        with PortalClient(self.settings, creds) as client:
            client.login()
            self._phase("Reading Elternbriefe")
            parsed_letters = parse_elternbriefe(client.get_elternbriefe_html(), client.base_url)

            for n, parsed in enumerate(parsed_letters, 1):
                self._phase(f"Downloading attachments ({n}/{len(parsed_letters)})")
                prev = state.letters.get(parsed.id)
                force = _needs_download(parsed, prev)
                prev_files = {a.repo: a for a in prev.attachments} if prev else {}

                used: set[str] = set()
                attachments: list[StoredAttachment] = []
                for att in parsed.attachments:
                    existing = prev_files.get(att.repo)
                    file = existing.file if existing else _unique_name(att.name, att.repo, used)
                    used.add(file)
                    path = self.storage.attachment_path(parsed.id, file)

                    if existing and not force and path.exists():
                        attachments.append(existing)
                        continue

                    content, _ = client.download(att.url)
                    atomic_write(path, content)
                    result.downloaded_files += 1
                    sha = hashlib.sha256(content).hexdigest()
                    keep_text = existing and existing.sha256 == sha
                    attachments.append(
                        existing.model_copy(update={"name": att.name, "size": len(content)})
                        if keep_text
                        else StoredAttachment(repo=att.repo, name=att.name, file=file, size=len(content), sha256=sha)
                    )

                changed = prev is None or force or prev.removed or prev.acknowledged != parsed.acknowledged
                state.letters[parsed.id] = StoredLetter(
                    **parsed.model_dump(exclude={"attachments"}),
                    attachments=attachments,
                    first_seen_at=prev.first_seen_at if prev else now,
                    updated_at=now if changed else prev.updated_at,
                    analysis=prev.analysis if prev else None,
                    analysis_error=prev.analysis_error if prev else None,
                    webhook_pending=prev.webhook_pending if prev else False,
                )
                self.storage.write_letter_md(state.letters[parsed.id])

                if prev is None:
                    result.new.append(parsed.id)
                elif changed:
                    result.updated.append(parsed.id)
                else:
                    result.unchanged.append(parsed.id)

        present = {p.id for p in parsed_letters}
        for letter_id, letter in state.letters.items():
            if letter_id not in present and not letter.removed:
                letter.removed = True
                letter.updated_at = now
                result.removed.append(letter_id)

        state.last_sync_at = _now()
        self.storage.save_state(state)

    def _process(
        self, state: State, cfg: AppConfig, result: SyncResult, only: set[str] | None, force: bool
    ) -> None:
        letters = sorted(
            (l for l in state.letters.values() if not l.removed and (only is None or l.id in only)),
            key=lambda l: l.number,
            reverse=True,
        )
        def text_key(att: StoredAttachment, method: str) -> str:
            return hashlib.sha256(f"{att.sha256}\n{method}".encode()).hexdigest()

        want_method = extract.method_for(cfg.pdf_ollama)

        for n, letter in enumerate(letters, 1):
            changed = False
            for att in letter.attachments:
                text_path = self.storage.attachment_path(letter.id, f"{att.file}.md")
                if not force and att.text_key == text_key(att, want_method) and text_path.exists():
                    continue
                self._phase(f"Reading attachment {att.name} ({n}/{len(letters)})")
                text, method, err = extract.extract_text(self.storage.attachment_path(letter.id, att.file), cfg.pdf_ollama)
                atomic_write(text_path, text.encode("utf-8"))
                att.text_file = text_path.name
                att.text_method = method
                # A failed Ollama run is cached as a plain text extraction so it is retried next time.
                att.text_key = text_key(att, "text" if err else want_method)
                att.text_error = err
                if err:
                    result.errors.append(f"{letter.id}/{att.name}: {err}")
                result.extracted_files += 1
                changed = True

            if cfg.context_ollama.active:
                key = analysis.input_key(letter, cfg.context_ollama)
                if force or letter.analysis is None or letter.analysis.input_key != key:
                    self._phase(f"Analysing «{letter.title}» ({n}/{len(letters)})")
                    texts = [(a.name, self.storage.attachment_text(letter.id, a)) for a in letter.attachments]
                    try:
                        letter.analysis = analysis.analyze(letter, texts, cfg.context_ollama, self.settings.tz)
                        letter.analysis_error = None
                        result.analyzed_letters += 1
                    except Exception as e:
                        letter.analysis_error = str(e)
                        result.errors.append(f"{letter.id}: {e}")
                        log.warning("Analysis failed for %s: %s", letter.id, e)
                    changed = True

            if changed:
                self.storage.write_letter_md(letter)
                self.storage.save_state(state)

    def _notify(self, state: State, cfg: AppConfig, result: SyncResult) -> None:
        """Sends pending new-letter webhooks; failed deliveries stay pending and are retried next sync."""
        pending = sorted((l for l in state.letters.values() if l.webhook_pending), key=lambda l: l.number)
        for letter in pending:
            if not cfg.webhook_url or letter.removed:
                letter.webhook_pending = False
                continue
            self._phase(f"Sending webhook for «{letter.title}»")
            base = urls.base_url()
            try:
                webhook.send(str(cfg.webhook_url), "letter.created",
                             webhook.letter_payload(letter, self.storage.render(letter, base_url=base), base))
                letter.webhook_pending = False
                result.webhooks_sent += 1
            except Exception as e:
                result.errors.append(f"webhook {letter.id}: {e}")
                log.warning("Webhook failed for %s: %s", letter.id, e)
        if pending:
            self.storage.save_state(state)
