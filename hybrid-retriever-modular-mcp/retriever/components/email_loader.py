"""Email ingest loader for the modular retriever.

Bridges the email-mcp output format (and raw .eml files) into the standard
Haystack indexing pipeline. The loader handles two inputs:

1. ``.eml`` file -- parsed via the Python stdlib ``email`` module. The body
   is preferred as ``text/plain`` and falls back to a naive HTML→text strip
   when only HTML parts are present. Attachments are listed (name + size +
   content-type) but their bytes are *not* embedded into the body, matching
   the local-only design of the retriever.

2. **Pre-converted email-mcp folder** -- a directory containing
   ``meta.json`` + ``body.md`` (the Phase-1 output of
   ``email-mcp/scripts/convert.py``). The unified markdown body is taken
   as-is so attachment text already inlined by email-mcp survives. This is
   how the retriever can ingest PST-decoded mail without itself requiring
   the ``libpff-python`` cp39 wheel that PST decoding needs.

Both modes emit:
    text             unified markdown (header block + body)
    path             resolved input path
    size_bytes       byte size on disk
    email_metadata   {subject, sender, recipients, date, folder_path, ...}

``run_indexing`` reads ``email_metadata`` from the loader output and merges
it into each emitted ``Document.meta["metadata"]`` so it stays searchable
via ``metadata_condition`` on the standard retrieval pipeline.
"""
from __future__ import annotations

import email
import email.policy
import json
import re
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from haystack import component


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|#39|nbsp);")
_HTML_ENTITIES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&nbsp;": " ",
}


@component
class EmailFileLoader:
    """Load an email source into unified markdown + structured metadata."""

    def __init__(self, max_chars: int = 2_000_000) -> None:
        self._max_chars = int(max_chars)

    @component.output_types(text=str, path=str, size_bytes=int, email_metadata=dict)
    def run(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser()
        if target.is_dir():
            text, meta = _load_converted_mail_dir(target, self._max_chars)
            size = _dir_size(target)
        elif target.suffix.lower() == ".eml" and target.is_file():
            text, meta = _load_eml(target, self._max_chars)
            size = target.stat().st_size
        else:
            raise FileNotFoundError(
                f"email loader expects a .eml file or a pre-converted mail directory "
                f"(meta.json + body.md); got: {target}"
            )
        return {
            "text": text,
            "path": str(target),
            "size_bytes": size,
            "email_metadata": meta,
        }


# ---------------------------------------------------------------------------
# email-mcp pre-converted directory
# ---------------------------------------------------------------------------

def _load_converted_mail_dir(mail_dir: Path, max_chars: int) -> tuple[str, dict[str, Any]]:
    meta_path = mail_dir / "meta.json"
    body_path = mail_dir / "body.md"
    if not meta_path.is_file() or not body_path.is_file():
        raise FileNotFoundError(
            f"mail directory missing meta.json or body.md: {mail_dir}"
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    body = body_path.read_text(encoding="utf-8")[:max_chars]
    email_meta = {
        "kind": "email",
        "source": "email_mcp_converted",
        "mail_id": meta.get("mail_id") or mail_dir.name,
        "subject": meta.get("subject", ""),
        "sender": meta.get("sender", ""),
        "recipients": meta.get("recipients", ""),
        "received": meta.get("received", ""),
        "folder_path": meta.get("folder_path", ""),
    }
    # body.md from email-mcp already contains a header block at the top -- do
    # not duplicate it. Just return the body as the unified text.
    return body, email_meta


# ---------------------------------------------------------------------------
# Raw .eml file
# ---------------------------------------------------------------------------

def _load_eml(eml_path: Path, max_chars: int) -> tuple[str, dict[str, Any]]:
    msg: EmailMessage = email.message_from_bytes(  # type: ignore[assignment]
        eml_path.read_bytes(), policy=email.policy.default
    )
    subject = _decode_header(msg.get("Subject", ""))
    sender = _decode_header(msg.get("From", ""))
    recipients = _decode_header(msg.get("To", ""))
    cc = _decode_header(msg.get("Cc", ""))
    date = _decode_header(msg.get("Date", ""))
    message_id = (msg.get("Message-ID") or "").strip()

    body_text = _extract_body_text(msg)

    attachments: list[dict[str, Any]] = []
    for part in msg.iter_attachments():
        try:
            filename = part.get_filename() or "attachment"
            content_type = part.get_content_type()
            data = part.get_payload(decode=True) or b""
            attachments.append({
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(data),
            })
        except Exception:
            continue

    unified = _build_unified_markdown(
        subject=subject,
        sender=sender,
        recipients=recipients,
        cc=cc,
        date=date,
        body=body_text,
        attachments=attachments,
    )[:max_chars]

    email_meta = {
        "kind": "email",
        "source": "eml",
        "mail_id": message_id or eml_path.stem,
        "subject": subject,
        "sender": sender,
        "recipients": recipients,
        "cc": cc,
        "received": date,
        "message_id": message_id,
        "attachment_count": len(attachments),
    }
    return unified, email_meta


def _decode_header(value: str) -> str:
    """Return a decoded header string. The stdlib default policy already
    returns ``str`` with RFC 2047 encoded-words handled, so just normalise
    whitespace and strip surrounding quotes here."""
    if not value:
        return ""
    return " ".join(str(value).split()).strip()


def _extract_body_text(msg: EmailMessage) -> str:
    """Return the best-effort plain-text body for a parsed message.

    Preference order: text/plain part(s) concatenated, then a strip of the
    first text/html part. Avoids ``msg.get_body(...)`` because it can
    surprise-pick HTML when both parts exist.
    """
    text_parts: list[str] = []
    html_parts: list[str] = []
    for part in msg.walk():
        if part.is_multipart() or part.is_attachment():
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            try:
                text_parts.append(part.get_content())
            except Exception:
                continue
        elif ctype == "text/html":
            try:
                html_parts.append(part.get_content())
            except Exception:
                continue
    if text_parts:
        return "\n\n".join(text_parts).strip()
    if html_parts:
        return _html_to_text("\n".join(html_parts))
    try:
        payload = msg.get_content()
        return payload if isinstance(payload, str) else ""
    except Exception:
        return ""


def _html_to_text(html: str) -> str:
    cleaned = _HTML_TAG_RE.sub(" ", html or "")

    def _entity(match: re.Match[str]) -> str:
        return _HTML_ENTITIES.get(match.group(0), " ")

    cleaned = _HTML_ENTITY_RE.sub(_entity, cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def _build_unified_markdown(
    *,
    subject: str,
    sender: str,
    recipients: str,
    cc: str,
    date: str,
    body: str,
    attachments: list[dict[str, Any]],
) -> str:
    """Mirror email-mcp's body.md header layout so search results carry the
    same context regardless of whether ingest came via a pre-converted dir
    or a raw .eml."""
    lines: list[str] = []
    lines.append(f"# {subject or '(no subject)'}")
    lines.append("")
    if sender:
        lines.append(f"- From: {sender}")
    if recipients:
        lines.append(f"- To: {recipients}")
    if cc:
        lines.append(f"- Cc: {cc}")
    if date:
        lines.append(f"- Date: {date}")
    lines.append("")
    lines.append("## Body")
    lines.append("")
    lines.append(body or "")
    if attachments:
        lines.append("")
        lines.append("## Attachments")
        for att in attachments:
            lines.append(
                f"- {att['filename']} ({att['content_type']}, "
                f"{att['size_bytes']} bytes)"
            )
    return "\n".join(lines)


def _dir_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total
