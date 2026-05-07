"""Convert mail body + PDF/DOCX attachments into a single unified markdown."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from markdownify import markdownify as html_to_md

log = logging.getLogger(__name__)

ATTACHMENT_HEADER = "\n\n---\n\n[첨부파일: {name}]\n\n"


def body_to_markdown(html: str, plain: str, max_chars: int) -> str:
    if html and html.strip():
        try:
            md = html_to_md(html, heading_style="ATX")
        except Exception as exc:  # pragma: no cover
            log.warning("markdownify failed, falling back to plain: %s", exc)
            md = plain or ""
    else:
        md = plain or ""
    return md.strip()[:max_chars]


def pdf_to_markdown(data: bytes, max_chars: int) -> str:
    import fitz  # pymupdf

    parts: list[str] = []
    used = 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            text = text.strip()
            if not text:
                continue
            chunk = f"### 페이지 {page_num}\n\n{text}\n"
            if used + len(chunk) > max_chars:
                parts.append(chunk[: max_chars - used])
                break
            parts.append(chunk)
            used += len(chunk)
    return "\n".join(parts)


def docx_to_markdown(data: bytes, max_chars: int) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    out: list[str] = []
    used = 0

    def push(line: str) -> bool:
        nonlocal used
        if used + len(line) + 1 > max_chars:
            out.append(line[: max_chars - used])
            return False
        out.append(line)
        used += len(line) + 1
        return True

    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "2"
            line = f"{'#' * min(int(level), 6)} {text}"
        else:
            line = text
        if not push(line):
            return "\n".join(out)

    for tbl_idx, table in enumerate(doc.tables, start=1):
        if not push(f"\n**표 {tbl_idx}**\n"):
            return "\n".join(out)
        for row in table.rows:
            cells = [(cell.text or "").strip().replace("\n", " ") for cell in row.cells]
            if not push("| " + " | ".join(cells) + " |"):
                return "\n".join(out)
    return "\n".join(out)


def attachment_to_markdown(filename: str, data: bytes, max_chars: int) -> str | None:
    """Return markdown text for an attachment, or None if format is unsupported."""
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            return pdf_to_markdown(data, max_chars)
        if suffix == ".docx":
            return docx_to_markdown(data, max_chars)
    except Exception as exc:
        log.warning("failed to parse attachment %s: %s", filename, exc)
        return None
    return None


def build_unified_markdown(
    subject: str,
    sender: str,
    received: str,
    folder_path: str,
    body_md: str,
    attachment_sections: list[tuple[str, str]],
) -> str:
    """Combine mail body + attachment markdown into one document."""
    header = (
        f"# {subject or '(제목 없음)'}\n\n"
        f"- **From:** {sender}\n"
        f"- **Received:** {received}\n"
        f"- **Folder:** {folder_path}\n\n"
        "---\n\n"
    )
    parts = [header, body_md.strip()]
    for filename, md in attachment_sections:
        parts.append(ATTACHMENT_HEADER.format(name=filename))
        parts.append(md.strip())
    return "\n".join(parts).strip() + "\n"
