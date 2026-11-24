import asyncio
import datetime as dt
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from epp import services, urls, webhook
from epp.agenda import DailySummary, LetterEvent, build_ics, collect_events, daily_markdown, events_between
from epp.appconfig import AppConfig, AppConfigUpdate, OllamaEndpoint, next_runs, validate_cron
from epp.client import AuthError, PortalClient
from epp.credentials import Credentials, credential_store
from epp.models import StoredLetter
from epp.ollama import OllamaError, list_models
from epp.sync import JobBusy, MissingCredentials

log = logging.getLogger(__name__)
settings, storage, config_store, runner, scheduler = (
    services.settings, services.storage, services.config_store, services.runner, services.scheduler,
)

from epp.mcp_server import mcp, mcp_app  # noqa: E402

_mcp_app = mcp_app()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(scheduler.run_forever())
    async with mcp.session_manager.run():
        yield
    task.cancel()


app = FastAPI(title="Eltern-Portal Parser", version="0.2.0", lifespan=lifespan)
app.add_middleware(urls.ForwardedMiddleware)


def _start(kind: str, letter_ids: list[str] | None = None) -> dict:
    try:
        runner.start(kind, letter_ids)
    except JobBusy as e:
        raise HTTPException(409, str(e))
    except MissingCredentials as e:
        raise HTTPException(428, str(e))
    return {"started": kind}


def _get_letter(letter_id: str) -> StoredLetter:
    letter = storage.load_state().letters.get(letter_id)
    if letter is None:
        raise HTTPException(404, "letter not found")
    return letter


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def get_status() -> dict:
    return services.status()


# Credentials (memory only)


class CredentialsIn(BaseModel):
    tenant: str
    username: str
    password: str


@app.get("/api/credentials")
def get_credentials() -> dict:
    return services.status()["credentials"]


@app.post("/api/credentials")
async def set_credentials(body: CredentialsIn) -> dict:
    try:
        creds = Credentials(**body.model_dump())
    except ValidationError as e:
        raise HTTPException(422, "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors()))

    def check() -> None:
        with PortalClient(settings, creds) as client:
            client.login()

    try:
        await asyncio.to_thread(check)
    except AuthError:
        raise HTTPException(401, "Login failed: check tenant, username and password")
    except Exception as e:
        raise HTTPException(502, f"Could not reach {creds.tenant}.{settings.base_domain}: {e}")

    credential_store.set(creds)
    try:
        runner.start("sync")
    except JobBusy:
        pass
    return services.status()["credentials"]


@app.delete("/api/credentials")
def clear_credentials() -> dict:
    credential_store.clear()
    return services.status()["credentials"]


# Configuration


@app.get("/api/config", response_model=AppConfig)
def get_config() -> AppConfig:
    return config_store.get()


@app.put("/api/config", response_model=AppConfig)
async def put_config(body: AppConfigUpdate) -> AppConfig:
    cfg = config_store.update(body)
    scheduler.reschedule()
    return cfg


@app.get("/api/config/cron-preview")
def cron_preview(expr: str) -> dict:
    try:
        expr = validate_cron(expr)
        runs = next_runs(expr, settings.tz, 5)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"expr": expr, "timezone": settings.timezone, "next_runs": runs}


class WebhookTest(BaseModel):
    url: str


@app.post("/api/config/webhook-test")
async def webhook_test(body: WebhookTest) -> dict:
    sample = next(iter(services.letters()), None)
    base = urls.base_url()
    data = webhook.letter_payload(sample, storage.render(sample, base_url=base), base) if sample else {}
    try:
        await asyncio.to_thread(webhook.send, body.url, "test", data)
    except Exception as e:
        raise HTTPException(502, f"Webhook failed: {e}")
    return {"ok": True}


@app.get("/api/ollama/models")
async def ollama_models(host: str, port: int = 11434) -> dict:
    endpoint = OllamaEndpoint(enabled=True, host=host, port=port)
    try:
        return {"base_url": endpoint.base_url, "models": await asyncio.to_thread(list_models, endpoint)}
    except OllamaError as e:
        raise HTTPException(502, str(e))


# Jobs


@app.post("/api/sync", status_code=202)
def trigger_sync() -> dict:
    return _start("sync")


@app.post("/api/process", status_code=202)
def trigger_process() -> dict:
    return _start("process")


@app.post("/api/letters/{letter_id}/reprocess", status_code=202)
def reprocess_letter(letter_id: str) -> dict:
    _get_letter(letter_id)
    return _start("reprocess", [letter_id])


# Letters


@app.get("/api/letters", response_model=list[StoredLetter])
def list_letters(include_removed: bool = False, q: str | None = None) -> list[StoredLetter]:
    return services.search_letters(q) if q else services.letters(include_removed)


@app.get("/api/letters.md", response_class=PlainTextResponse)
def all_letters_markdown() -> PlainTextResponse:
    state = storage.load_state()
    if not state.letters:
        raise HTTPException(404, "no data yet, run a sync first")
    return PlainTextResponse(storage.render_all(state, base_url=urls.base_url()), media_type="text/markdown")


@app.get("/api/letters/{letter_id}", response_model=StoredLetter)
def get_letter(letter_id: str) -> StoredLetter:
    return _get_letter(letter_id)


@app.get("/api/letters/{letter_id}/markdown", response_class=PlainTextResponse)
def get_letter_markdown(letter_id: str) -> PlainTextResponse:
    return PlainTextResponse(storage.render(_get_letter(letter_id), base_url=urls.base_url()),
                             media_type="text/markdown")


def _attachment(letter_id: str, repo: str):
    letter = _get_letter(letter_id)
    att = next((a for a in letter.attachments if a.repo == repo), None)
    if att is None:
        raise HTTPException(404, "attachment not found")
    return letter, att


@app.get("/api/letters/{letter_id}/attachments/{repo}")
def get_attachment(letter_id: str, repo: str, download: bool = False) -> FileResponse:
    letter, att = _attachment(letter_id, repo)
    path = storage.attachment_path(letter.id, att.file)
    if not path.exists():
        raise HTTPException(404, "attachment file missing, run a sync")
    media_type = mimetypes.guess_type(att.file)[0] or "application/octet-stream"
    disposition = "attachment" if download else "inline"
    return FileResponse(path, filename=att.name, media_type=media_type, content_disposition_type=disposition)


@app.get("/api/letters/{letter_id}/attachments/{repo}/text", response_class=PlainTextResponse)
def get_attachment_text(letter_id: str, repo: str) -> PlainTextResponse:
    letter, att = _attachment(letter_id, repo)
    return PlainTextResponse(storage.attachment_text(letter.id, att), media_type="text/markdown")


# Calendar


@app.get("/api/events", response_model=list[LetterEvent])
def list_events(
    start: dt.date | None = Query(None, alias="from"), end: dt.date | None = Query(None, alias="to")
) -> list[LetterEvent]:
    events = collect_events(storage.load_state())
    if start or end:
        events = events_between(events, start or dt.date.min, end or dt.date.max)
    return events


@app.get("/api/daily", response_model=DailySummary)
def get_daily(date: dt.date | None = None) -> DailySummary:
    return services.daily(date)


@app.get("/api/daily.md", response_class=PlainTextResponse)
def get_daily_markdown(date: dt.date | None = None) -> PlainTextResponse:
    return PlainTextResponse(daily_markdown(services.daily(date)), media_type="text/markdown")


@app.get("/ics/{token}.ics")
def ics_feed(token: str) -> Response:
    if token != config_store.get().ics_token:
        raise HTTPException(404, "not found")
    base = urls.base_url()
    letter_url = f"{base}/#/letters/{{id}}" if base else None
    body = build_ics(storage.load_state(), settings.tz, letter_url)
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="eltern-portal.ics"'})


@app.get("/mcp", include_in_schema=False)
def mcp_get() -> JSONResponse:
    # The server is stateless and never pushes messages, so instead of an SSE stream that stays open
    # forever, answer GET with 405 as the Streamable HTTP spec allows.
    return JSONResponse(
        {
            "error": "MCP endpoint: send JSON-RPC requests with POST",
            "transport": "streamable-http",
            "example": (
                "curl -X POST <this-url> -H 'Content-Type: application/json' "
                "-H 'Accept: application/json, text/event-stream' "
                "-d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"
            ),
        },
        status_code=405,
        headers={"Allow": "POST"},
    )


app.router.routes.extend(r for r in _mcp_app.routes)

if settings.static_dir and settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="web")
