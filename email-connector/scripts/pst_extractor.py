"""PST → message records via pypff. Yields per-message dicts."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

import pypff

log = logging.getLogger(__name__)


@dataclass
class Attachment:
    filename: str
    data: bytes


@dataclass
class MailMessage:
    mail_id: str
    subject: str
    sender: str
    recipients: str
    received: str  # ISO 8601, UTC
    folder_path: str
    body_html: str
    body_plain: str
    attachments: list[Attachment] = field(default_factory=list)


def _safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for enc in ("utf-8", "cp1252", "cp949", "latin-1"):
            try:
                return value.decode(enc)
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="replace")
    return str(value)


def _format_received(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _make_mail_id(subject: str, received: str, sender: str, identifier: int | None) -> str:
    raw = f"{identifier}|{subject}|{received}|{sender}".encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()[:20]


def _rtf_fallback(message) -> str:
    """Some mails store body only as compressed RTF. pypff decompresses it for us;
    we strip RTF control words to plain text via striprtf."""
    try:
        rtf = message.get_rtf_body()
    except Exception:
        return ""
    if not rtf:
        return ""
    if isinstance(rtf, bytes):
        rtf = rtf.decode("latin-1", errors="replace")
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        log.warning("striprtf not installed; RTF-only body will be skipped")
        return ""
    try:
        return rtf_to_text(rtf, errors="ignore").strip()
    except Exception as exc:
        log.warning("striprtf failed: %s", exc)
        return ""


def _extract_attachments(message) -> list[Attachment]:
    out: list[Attachment] = []
    try:
        count = message.get_number_of_attachments()
    except Exception:
        return out
    for i in range(count):
        try:
            att = message.get_attachment(i)
            name = _safe_str(getattr(att, "name", "") or f"attachment_{i}")
            size = att.get_size() if hasattr(att, "get_size") else 0
            data = att.read_buffer(size) if size and hasattr(att, "read_buffer") else b""
            out.append(Attachment(filename=name, data=data or b""))
        except Exception as exc:  # pragma: no cover - depends on PST contents
            log.warning("failed to read attachment %d: %s", i, exc)
    return out


def _walk_folder(folder, path: str) -> Iterator[tuple[str, object]]:
    name = _safe_str(getattr(folder, "name", "")) or "(root)"
    here = f"{path}/{name}" if path else name
    try:
        for i in range(folder.get_number_of_sub_messages()):
            yield here, folder.get_sub_message(i)
    except Exception as exc:
        log.warning("failed to enumerate messages in %s: %s", here, exc)
    try:
        for i in range(folder.get_number_of_sub_folders()):
            yield from _walk_folder(folder.get_sub_folder(i), here)
    except Exception as exc:
        log.warning("failed to recurse into %s: %s", here, exc)


def iter_messages(pst_path: str) -> Iterator[MailMessage]:
    """Open a PST and yield MailMessage objects for every email found."""
    pst = pypff.file()
    pst.open(pst_path)
    try:
        root = pst.get_root_folder()
        for folder_path, msg in _walk_folder(root, ""):
            try:
                subject = _safe_str(msg.get_subject())
                sender = _safe_str(msg.get_sender_name())
                received = _format_received(msg.get_delivery_time())
                identifier = getattr(msg, "identifier", None)
                body_html = _safe_str(getattr(msg, "html_body", None) or msg.get_html_body())
                body_plain = _safe_str(getattr(msg, "plain_text_body", None) or msg.get_plain_text_body())
                if not body_html.strip() and not body_plain.strip():
                    body_plain = _rtf_fallback(msg)
                recipients = _safe_str(getattr(msg, "transport_headers", "") or "")
                yield MailMessage(
                    mail_id=_make_mail_id(subject, received, sender, identifier),
                    subject=subject,
                    sender=sender,
                    recipients=recipients,
                    received=received,
                    folder_path=folder_path,
                    body_html=body_html,
                    body_plain=body_plain,
                    attachments=_extract_attachments(msg),
                )
            except Exception as exc:
                log.warning("skipped malformed message in %s: %s", folder_path, exc)
                continue
    finally:
        pst.close()
