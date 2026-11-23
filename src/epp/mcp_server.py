import datetime as dt

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from epp import services, urls
from epp.agenda import collect_events, daily_markdown, events_between
from epp.storage import format_event
from epp.sync import JobBusy, MissingCredentials

mcp = MCPServer(
    name="eltern-portal",
    title="Eltern-Portal",
    instructions=(
        "Access to school letters (Elternbriefe) from the Eltern-Portal: letters with summaries, "
        "attachment text, extracted appointments and a daily overview."
    ),
)


def _letter_line(letter) -> str:
    date = letter.published_at.strftime("%d.%m.%Y") if letter.published_at else "-"
    summary = f" – {letter.analysis.summary}" if letter.analysis and letter.analysis.summary else ""
    files = f" [{len(letter.attachments)} Anhang/Anhänge]" if letter.attachments else ""
    return f"- #{letter.number} (id {letter.id}, {date}) {letter.title}{files}{summary}"


@mcp.tool(description="List the most recent school letters with id, date, title and summary.")
def list_letters(limit: int = 20) -> str:
    letters = services.letters()[: max(1, limit)]
    return "\n".join(_letter_line(l) for l in letters) or "No letters synced yet."


@mcp.tool(description="Get one letter as Markdown including summary, key facts, appointments and attachment text.")
def get_letter(letter_id: str) -> str:
    letter = services.storage.load_state().letters.get(letter_id)
    if letter is None:
        return f"Letter {letter_id} not found."
    return services.storage.render(letter, base_url=urls.base_url())


@mcp.tool(description="Full-text search over letters, summaries and attachment text. All words must match.")
def search_letters(query: str) -> str:
    found = services.search_letters(query)
    return "\n".join(_letter_line(l) for l in found) or "No matching letters."


@mcp.tool(
    description=(
        "Daily overview with two sections: today and the rest of the current week. "
        "On Saturday and Sunday it covers Monday and the coming week. Optional date as YYYY-MM-DD."
    )
)
def get_daily_summary(date: str | None = None) -> str:
    day = dt.date.fromisoformat(date) if date else None
    return daily_markdown(services.daily(day))


@mcp.tool(description="List appointments and deadlines between two dates (YYYY-MM-DD, inclusive).")
def list_events(start: str, end: str) -> str:
    events = events_between(
        collect_events(services.storage.load_state()), dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    )
    return "\n".join(f"- {format_event(le.event)} (Elternbrief #{le.letter_number}, id {le.letter_id})"
                     for le in events) or "No appointments in this range."


@mcp.tool(description="Show sync status, last sync time and next scheduled run.")
def get_status() -> dict:
    return services.status()


@mcp.tool(description="Start a sync with the Eltern-Portal now (runs in the background).")
def trigger_sync() -> str:
    try:
        services.runner.start("sync")
    except (JobBusy, MissingCredentials) as e:
        return f"Not started: {e}"
    return "Sync started."


def mcp_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
