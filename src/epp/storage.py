import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from epp.models import Event, State, StoredAttachment, StoredLetter, newest_first

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(name: str, fallback: str) -> str:
    name = _UNSAFE_CHARS.sub("_", name).strip().strip(".")
    return name or fallback


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.state_path = data_dir / "state.json"
        self.letters_dir = data_dir / "letters"
        self.combined_md_path = data_dir / "elternbriefe.md"

    def letter_dir(self, letter_id: str) -> Path:
        return self.letters_dir / safe_filename(letter_id, "unknown")

    def letter_md_path(self, letter_id: str) -> Path:
        return self.letter_dir(letter_id) / "letter.md"

    def attachment_path(self, letter_id: str, file: str) -> Path:
        path = (self.letter_dir(letter_id) / file).resolve()
        if path.parent != self.letter_dir(letter_id).resolve():
            raise ValueError("invalid attachment path")
        return path

    def attachment_text(self, letter_id: str, att: StoredAttachment) -> str:
        if not att.text_file:
            return ""
        path = self.attachment_path(letter_id, att.text_file)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def load_state(self) -> State:
        if not self.state_path.exists():
            return State()
        return State.model_validate_json(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: State) -> None:
        atomic_write(self.state_path, state.model_dump_json(indent=2).encode("utf-8"))

    def render(self, letter: StoredLetter, heading_level: int = 1, base_url: str | None = None,
               link_prefix: str = "") -> str:
        """With base_url, attachment links point to the HTTP API; otherwise to files next to letter.md."""
        texts = {a.repo: self.attachment_text(letter.id, a) for a in letter.attachments}
        if base_url:
            def link(a: StoredAttachment) -> str:
                return f"{base_url}/api/letters/{quote(letter.id)}/attachments/{quote(a.repo)}"
        else:
            def link(a: StoredAttachment) -> str:
                return f"{link_prefix}{a.file}"
        return render_letter_md(letter, texts, heading_level, link)

    def render_all(self, state: State, base_url: str | None = None) -> str:
        letters = newest_first(l for l in state.letters.values() if not l.removed)
        parts = ["# Elternbriefe & Schwarzes Brett", *(
            self.render(l, heading_level=2, base_url=base_url, link_prefix=f"letters/{l.id}/") for l in letters
        )]
        return "\n\n---\n\n".join(parts) + "\n"

    def write_letter_md(self, letter: StoredLetter) -> None:
        atomic_write(self.letter_md_path(letter.id), self.render(letter).encode("utf-8"))

    def write_combined_md(self, state: State) -> None:
        atomic_write(self.combined_md_path, self.render_all(state).encode("utf-8"))


def format_event(e: Event) -> str:
    when = e.date.strftime("%d.%m.%Y")
    if e.end_date:
        when += f" – {e.end_date:%d.%m.%Y}"
    if e.start_time:
        when += f", {e.start_time}" + (f"–{e.end_time}" if e.end_time else "")
    text = f"**{when}:** {e.title}"
    if e.location:
        text += f" ({e.location})"
    if e.details:
        text += f" – {e.details}"
    return text


def render_letter_md(
    letter: StoredLetter,
    texts: dict[str, str] | None = None,
    heading_level: int = 1,
    link: Callable[[StoredAttachment], str] | None = None,
) -> str:
    texts = texts or {}
    link = link or (lambda a: a.file)
    h = "#" * heading_level
    date = letter.published_at.strftime("%d.%m.%Y %H:%M") if letter.published_at else "-"
    lines = [
        f"{h} {letter.label} {letter.title}",
        "",
        f"- **ID:** {letter.id}",
        f"- **Quelle:** {'Elternbrief' if letter.kind == 'letter' else 'Schwarzes Brett'}",
        f"- **Datum:** {date}",
    ]
    if letter.kind == "letter":
        lines += [
            f"- **Klasse/n:** {', '.join(letter.classes) or '-'}",
            f"- **Empfang bestätigt:** {'ja' if letter.acknowledged else 'nein'}",
        ]
    lines.append(f"- **SHA-256 (Beschreibung):** `{letter.description_sha256}`")

    if letter.analysis:
        a = letter.analysis
        lines += ["", f"{h}# Zusammenfassung", "", a.summary or "-"]
        if a.key_facts:
            lines += ["", f"{h}# Wichtigste Fakten", "", *(f"- {f}" for f in a.key_facts)]
        if a.events:
            lines += ["", f"{h}# Termine", "", *(f"- {format_event(e)}" for e in a.events)]

    lines += ["", f"{h}# Anhänge", ""]
    if letter.attachments:
        lines += [f"- [{a.name}](<{link(a)}>)" for a in letter.attachments]
    else:
        lines.append("_Keine Anhänge_")
    lines += ["", f"{h}# Beschreibung", "", letter.description_md or "_Keine Beschreibung_"]

    for a in letter.attachments:
        text = texts.get(a.repo, "").strip()
        if text:
            lines += ["", f"{h}# Anhang: {a.name}", "", text]
    return "\n".join(lines)
