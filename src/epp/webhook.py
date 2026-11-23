import datetime as dt
import logging
from urllib.parse import quote

import httpx

from epp.models import StoredLetter

log = logging.getLogger(__name__)


def letter_payload(letter: StoredLetter, markdown: str, base_url: str | None = None) -> dict:
    """base_url is the public URL of this app; without it the payload carries no links."""
    a = letter.analysis
    api = f"{base_url}/api/letters/{quote(letter.id)}" if base_url else None
    return {
        "id": letter.id,
        "number": letter.number,
        "title": letter.title,
        "published_at": letter.published_at.isoformat() if letter.published_at else None,
        "classes": letter.classes,
        "url": f"{base_url}/#/letters/{quote(letter.id)}" if base_url else None,
        "markdown_url": f"{api}/markdown" if api else None,
        "description_md": letter.description_md,
        "description_sha256": letter.description_sha256,
        "summary": a.summary if a else None,
        "key_facts": a.key_facts if a else [],
        "events": [e.model_dump(mode="json") for e in a.events] if a else [],
        "attachments": [
            {"name": att.name, "repo": att.repo, "size": att.size,
             "url": f"{api}/attachments/{quote(att.repo)}" if api else None}
            for att in letter.attachments
        ],
        "markdown": markdown,
    }


def send(url: str, event: str, data: dict) -> None:
    body = {"event": event, "sent_at": dt.datetime.now(dt.timezone.utc).isoformat(), "data": data}
    resp = httpx.post(url, json=body, timeout=15.0, headers={"User-Agent": "epp-webhook/0.2"})
    resp.raise_for_status()
