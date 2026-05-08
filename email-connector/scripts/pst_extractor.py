"""PST → message records via pypff. Yields per-message dicts."""
from __future__ import annotations

import hashlib
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# libpff-python ships only a cp39-win_amd64 wheel (version 20211114). Importing
# pypff from any other interpreter either fails with ImportError ("DLL load
# failed", "no module named pypff") or pulls a stale build. Fail fast with a
# message that tells the operator exactly how to invoke the script.
if sys.version_info[:2] != (3, 9):
    raise RuntimeError(
        "email-connector requires Python 3.9 (got "
        f"{sys.version_info.major}.{sys.version_info.minor}). "
        "The libpff-python wheel only exists for cp39-win_amd64. "
        "Run scripts with the explicit launcher selector: "
        "`py -3.9 scripts\\<name>.py` — never plain `python` or `py`."
    )

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


def _sniff_zip_subtype(data: bytes) -> str:
    """Distinguish docx / xlsx / pptx / generic zip by peeking at zip entries."""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except Exception:
        return ".zip"
    if any(n.startswith("word/") for n in names):
        return ".docx"
    if any(n.startswith("xl/") for n in names):
        return ".xlsx"
    if any(n.startswith("ppt/") for n in names):
        return ".pptx"
    return ".zip"


def _sniff_ole_subtype(data: bytes) -> str:
    """OLE compound document → .msg / .xls / .ppt / .doc by stream-name heuristic.

    OLE compound files store streams whose names are visible as ASCII (UTF-16LE
    actually, but the high bytes are zeros for ASCII characters) in the FAT/MiniFAT
    structure. We don't fully parse the compound; we just look for known stream
    name fragments in the first 32 KB. Cheap, no extra deps.
    """
    head = data[: 32 * 1024]
    # MAPI .msg files always have these substorage / property stream prefixes
    if b"_" * 0 + b"_" + b"_substg1.0_" in head or b"__nameid_version1.0" in head:
        return ".msg"
    # Excel: "Workbook" (XLS BIFF8) or older "Book"
    if b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k" in head or b"Workbook" in head:
        return ".xls"
    # PowerPoint: "PowerPoint Document" stream
    if b"P\x00o\x00w\x00e\x00r\x00P\x00o\x00i\x00n\x00t" in head or b"PowerPoint Document" in head:
        return ".ppt"
    # Word: "WordDocument" stream
    if b"W\x00o\x00r\x00d\x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t" in head or b"WordDocument" in head:
        return ".doc"
    return ".doc"  # safe default for unidentified OLE


def _sniff_zip_subtype(data: bytes) -> str:
    """Distinguish docx / xlsx / pptx / generic zip by peeking at zip entries."""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except Exception:
        return ".zip"
    if any(n.startswith("word/") for n in names):
        return ".docx"
    if any(n.startswith("xl/") for n in names):
        return ".xlsx"
    if any(n.startswith("ppt/") for n in names):
        return ".pptx"
    return ".zip"


def _sniff_extension(data: bytes) -> str:
    """Best-effort extension from magic bytes. Returns '' if unknown."""
    if not data:
        return ""
    if data.startswith(b"%PDF"):
        return ".pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".mp4"
    if data.startswith(b"PK\x03\x04"):
        return _sniff_zip_subtype(data)
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _sniff_ole_subtype(data)
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return ".7z"
    if data.startswith(b"Rar!\x1a\x07"):
        return ".rar"
    if data.startswith(b"\x1f\x8b"):
        return ".gz"
    if data.startswith(b"%!PS"):
        return ".ps"
    if data.startswith(b"{\\rtf"):
        return ".rtf"
    return ""


# pypff exposes attachment metadata under different attribute names depending on
# what the PST source stored. PR_ATTACH_LONG_FILENAME (long_filename) carries
# the real filename with extension; PR_DISPLAY_NAME (often just "name") is a
# label that frequently has NO extension. Try the long form first.
_ATT_NAME_ATTRS = (
    "long_filename",
    "get_long_filename",
    "filename",
    "get_filename",
    "name",
    "get_name",
    "display_name",
    "get_display_name",
)

# Suffixes that carry no useful type information — treat them as "no extension"
# so the magic-byte sniffer can override.
_PLACEHOLDER_SUFFIXES = {".bin", ".dat", ".tmp", ".001", ".002", ".003", ".004", ".005"}


def _resolve_attachment_name(att, idx: int) -> str:
    """Pick the most informative filename pypff exposes for this attachment.

    Strategy:
      1. Collect every non-empty candidate from the attribute list above.
      2. Prefer candidates that carry a real (non-placeholder) suffix.
      3. Otherwise return the longest candidate.
      4. If nothing works, fall back to attachment_<idx>.
    """
    candidates: list[str] = []
    for attr in _ATT_NAME_ATTRS:
        if not hasattr(att, attr):
            continue
        v = getattr(att, attr)
        if callable(v):
            try:
                v = v()
            except Exception:
                continue
        s = _safe_str(v).strip()
        if s and s not in candidates:
            candidates.append(s)
    if not candidates:
        return f"attachment_{idx}"
    with_real = [c for c in candidates if _has_real_suffix(c)]
    if with_real:
        return max(with_real, key=len)
    return max(candidates, key=len)


def _has_real_suffix(name: str) -> bool:
    """True if Path(name).suffix is non-empty AND not a placeholder like .bin/.dat."""
    suf = Path(name).suffix.lower()
    if not suf or suf == ".":
        return False
    if suf in _PLACEHOLDER_SUFFIXES:
        return False
    return True


def _extract_attachments(message) -> list[Attachment]:
    out: list[Attachment] = []
    try:
        count = message.get_number_of_attachments()
    except Exception:
        return out
    for i in range(count):
        try:
            att = message.get_attachment(i)
            size = att.get_size() if hasattr(att, "get_size") else 0
            data = att.read_buffer(size) if size and hasattr(att, "read_buffer") else b""
            name = _resolve_attachment_name(att, i)
            # If the chosen name lacks a real suffix (display-name only, or a
            # placeholder like .bin/.dat), let magic bytes decide the suffix.
            if not _has_real_suffix(name) and data:
                ext = _sniff_extension(data)
                if ext:
                    if Path(name).suffix:  # replace placeholder suffix
                        name = str(Path(name).with_suffix(ext))
                    else:
                        name = name + ext
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
