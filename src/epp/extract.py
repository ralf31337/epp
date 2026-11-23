"""Turns attachments (PDFs, images) into Markdown text."""

import io
import logging
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from epp import ollama
from epp.appconfig import OllamaEndpoint

log = logging.getLogger(__name__)

MAX_PAGES = 20
RENDER_SCALE = 2.0
MAX_IMAGE_EDGE = 1800
MIN_TEXT_LAYER_CHARS = 200
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

VISION_PROMPT = (
    "Transcribe this document page to Markdown. Keep the original language. "
    "Preserve headings, lists, tables, names, dates, times and amounts exactly. "
    "Do not add comments or explanations; output only the Markdown. "
    "If the page is empty, output nothing."
)


def method_for(endpoint: OllamaEndpoint) -> str:
    """Identifies the configured extraction so results can be cached and redone when it changes."""
    return f"ollama:{endpoint.model}:{endpoint.mode}" if endpoint.active else "text"


def _png(img: Image.Image) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _vision(endpoint: OllamaEndpoint, image: bytes, label: str) -> str:
    log.info("Vision transcription of %s with %s", label, endpoint.model)
    return ollama.chat(endpoint, VISION_PROMPT, images=[image]).strip()


def _extract_pdf(path: Path, endpoint: OllamaEndpoint) -> tuple[str, str, str | None]:
    pdf = pdfium.PdfDocument(path)
    try:
        count = min(len(pdf), MAX_PAGES)
        pages: list[str] = []
        vision_pages = 0
        error = None
        for i in range(count):
            page = pdf[i]
            text = page.get_textpage().get_text_bounded().replace("\r\n", "\n").strip()
            wants_vision = endpoint.active and error is None and (
                endpoint.mode == "always" or len(text) < MIN_TEXT_LAYER_CHARS
            )
            if wants_vision:
                try:
                    image = _png(page.render(scale=RENDER_SCALE).to_pil())
                    text = _vision(endpoint, image, f"{path.name} page {i + 1}/{count}") or text
                    vision_pages += 1
                except Exception as e:
                    error = str(e)
                    log.warning("Ollama extraction failed for %s, using text layer: %s", path.name, e)
            if text:
                pages.append(text)
    finally:
        pdf.close()

    if vision_pages == count:
        method = f"ollama:{endpoint.model}"
    elif vision_pages:
        method = f"text+ollama:{endpoint.model} ({vision_pages}/{count} pages)"
    else:
        method = "text"
    return "\n\n---\n\n".join(pages), method, error


def extract_text(path: Path, endpoint: OllamaEndpoint) -> tuple[str, str, str | None]:
    """Returns (markdown, method used, error if Ollama failed and a fallback was used)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path, endpoint)
    if suffix in IMAGE_SUFFIXES and endpoint.active:
        try:
            return _vision(endpoint, _png(Image.open(path)), path.name), f"ollama:{endpoint.model}", None
        except Exception as e:
            log.warning("Ollama extraction failed for %s: %s", path.name, e)
            return "", "unsupported", str(e)
    return "", "unsupported", None
