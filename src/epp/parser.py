"""Rule-based parsers for the Eltern-Portal "Elternbriefe" and "Schwarzes Brett" pages.

Elternbriefe: each letter is rendered as two consecutive <tr> rows:
  1. <td>#N</td><td id="empf_<id>">Empfang bestätigt.</td>
  2. <td colspan=2> title link (<h4> + date), 0-n attachment links,
     <span class="small text">Klasse/n: ...</span>, description HTML </td>

Schwarzes Brett: current notices are `.grid-item .well` boxes ("eingestellt am DD.MM.YYYY HH:MM:SS",
<h4> title, body, attachment links); archived ones are `.row.arch .well` boxes with two rows
(display period "DD.MM.YYYY - DD.MM.YYYY" + <h4> title, then body and "Anhang:" links). Notices carry
no portal id or number.
"""

import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify

from epp.models import ParsedAttachment, ParsedLetter

TZ = ZoneInfo("Europe/Berlin")
_NUMBER_RE = re.compile(r"^#(\d+)$")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}):(\d{2})")
_EB_ID_RE = re.compile(r"eb_bestaetigung\((\d+)\)")
_NOTICE_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?")


def html_to_markdown(html: str) -> str:
    md = markdownify(html, heading_style="ATX", bullets="-", newline_style="backslash")
    md = md.replace("\xa0", " ")
    lines = [line.rstrip() for line in md.splitlines()]
    # Hard breaks ("\") that end a paragraph or stand alone are just noise.
    cleaned: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == "\\":
            line = ""
        elif line.endswith("\\"):
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt in ("", "\\"):
                line = line[:-1].rstrip()
        cleaned.append(line)
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_date(text: str) -> datetime | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mo, y, h, mi = map(int, m.groups())
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def _repo_of(href: str) -> str | None:
    return parse_qs(urlparse(href).query).get("repo", [None])[0]


def _attachments(el: Tag, base_url: str) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    seen: set[str] = set()
    for a in el.select("a.dynamic-file"):
        if "link_nachrichten" in a.get("class", []):
            continue  # title link duplicates the first attachment
        href = a.get("href", "")
        repo = _repo_of(href)
        if not repo or repo in seen:
            continue
        seen.add(repo)
        attachments.append(
            ParsedAttachment(repo=repo, name=a.get_text(" ", strip=True), url=urljoin(base_url + "/", href))
        )
    return attachments


def _parse_content_cell(td: Tag, base_url: str) -> dict:
    title_el = td.select_one(".link_nachrichten")
    h4 = td.find("h4")
    title = h4.get_text(" ", strip=True) if h4 else ""
    published_at = _parse_date(title_el.get_text(" ", strip=True)) if title_el else None

    eb_id = None
    if title_el and (m := _EB_ID_RE.search(title_el.get("onclick", ""))):
        eb_id = m.group(1)

    attachments = _attachments(td, base_url)

    classes: list[str] = []
    meta = td.select_one("span.small")
    if meta:
        meta_text = meta.get_text(" ", strip=True)
        if ":" in meta_text:
            classes = [c.strip() for c in meta_text.split(":", 1)[1].split(",") if c.strip()]

    anchor = meta or (td.select("a.dynamic-file") or [title_el])[-1]
    desc_html = ""
    if anchor is not None:
        desc_html = "".join(str(n) for n in anchor.next_siblings if isinstance(n, (Tag, NavigableString)))

    return {
        "eb_id": eb_id,
        "title": title,
        "published_at": published_at,
        "classes": classes,
        "attachments": attachments,
        "description_md": html_to_markdown(desc_html),
    }


def parse_elternbriefe(html: str, base_url: str) -> list[ParsedLetter]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("#asam_content table")
    if table is None:
        return []

    letters: list[ParsedLetter] = []
    rows = table.find_all("tr")
    i = 0
    while i < len(rows) - 1:
        cells = rows[i].find_all("td", recursive=False)
        m = _NUMBER_RE.match(cells[0].get_text(strip=True)) if cells else None
        if not m:
            i += 1
            continue

        number = int(m.group(1))
        status_td = cells[1] if len(cells) > 1 else None
        status_text = status_td.get_text(" ", strip=True).lower() if status_td else ""
        acknowledged = "bestätigt" in status_text and "nicht" not in status_text
        status_id = (status_td.get("id") or "").removeprefix("empf_") if status_td else ""

        content_td = rows[i + 1].find("td")
        data = _parse_content_cell(content_td, base_url)
        letter_id = data["eb_id"] or status_id or f"n{number}"

        letters.append(
            ParsedLetter(
                id=letter_id,
                number=number,
                title=data["title"],
                published_at=data["published_at"],
                classes=data["classes"],
                acknowledged=acknowledged,
                description_md=data["description_md"],
                description_sha256=sha256_text(data["description_md"]),
                attachments=data["attachments"],
            )
        )
        i += 2

    return letters


def _notice_date(text: str) -> tuple[str, datetime | None]:
    """Returns the date as DD.MM.YYYY (part of the notice id) and the full timestamp."""
    m = _NOTICE_DATE_RE.search(text)
    if not m:
        return "", None
    d, mo, y = map(int, m.group(1, 2, 3))
    h, mi = (int(m.group(4)), int(m.group(5))) if m.group(4) else (0, 0)
    return m.group(0)[:10], datetime(y, mo, d, h, mi, tzinfo=TZ)


def _notice_body(el: Tag, base_url: str) -> tuple[list[ParsedAttachment], str]:
    attachments = _attachments(el, base_url)
    for a in el.select("a.dynamic-file"):
        a.decompose()
    for p in el.find_all("p"):
        text = p.get_text(" ", strip=True)
        if text == "Anhang:" or (not text and not p.find(True)):
            p.decompose()
    return attachments, html_to_markdown(el.decode_contents())


def _notice(day: str, published_at: datetime | None, title: str, body: Tag | None, base_url: str,
            used_ids: set[str]) -> ParsedLetter:
    attachments, description = _notice_body(body, base_url) if body is not None else ([], "")
    base_id = "sb-" + hashlib.sha1(f"{day}|{title}".encode()).hexdigest()[:10]
    notice_id, n = base_id, 1
    while notice_id in used_ids:
        n += 1
        notice_id = f"{base_id}-{n}"
    used_ids.add(notice_id)
    return ParsedLetter(
        id=notice_id,
        kind="notice",
        number=0,  # assigned when stored, the portal has no numbers for notices
        title=title,
        published_at=published_at,
        classes=[],
        acknowledged=True,
        description_md=description,
        description_sha256=sha256_text(description),
        attachments=attachments,
    )


def parse_schwarzes_brett(html: str, base_url: str) -> list[ParsedLetter]:
    """Current notices first, then the archive, each newest first as on the page."""
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("#asam_content")
    if content is None:
        return []
    notices: list[ParsedLetter] = []
    used: set[str] = set()

    for well in content.select(".grid-item .well"):
        h4 = well.find("h4")
        stamp = well.select_one("p.text-right")
        day, published_at = _notice_date(stamp.get_text(" ", strip=True)) if stamp else ("", None)
        title = h4.get_text(" ", strip=True) if h4 else ""
        for el in (h4, stamp):
            if el is not None:
                el.decompose()
        notices.append(_notice(day, published_at, title, well, base_url, used))

    for well in content.select(".row.arch .well"):
        rows = well.find_all("div", class_="row", recursive=False)
        if not rows:
            continue
        h4 = rows[0].find("h4")
        period = rows[0].find("p")
        day, published_at = _notice_date(period.get_text(" ", strip=True)) if period else ("", None)
        body = rows[1].select_one(".col-sm-9") if len(rows) > 1 else None
        notices.append(_notice(day, published_at, h4.get_text(" ", strip=True) if h4 else "", body, base_url, used))

    return notices
