"""Email source loader for the modular retriever.

Handles .pst (via Python 3.9 worker), .eml, and pre-converted directories.
Emits a list of raw email data dicts to be processed by EmailMarkdownConverter.
"""
from __future__ import annotations
import email
import email.policy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, List
from haystack import component

@component
class EmailSourceLoader:
    """Loads emails from PST, EML, or converted directories into raw data dicts."""

    def __init__(self, worker_path: str | None = None):
        # Default worker path relative to the project root
        if worker_path is None:
            self.worker_path = str(Path(__file__).parent.parent / "scripts" / "pst_worker.py")
        else:
            self.worker_path = worker_path

    @component.output_types(raw_emails=List[dict[str, Any]], path=str)
    def run(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser()
        raw_emails = []

        if target.suffix.lower() == ".pst" and target.is_file():
            raw_emails = self._load_pst(target)
        elif target.suffix.lower() == ".eml" and target.is_file():
            raw_emails = [self._load_eml(target)]
        elif target.is_dir():
            raw_emails = [self._load_converted_dir(target)]
        else:
            raise FileNotFoundError(f"Unsupported email source: {target}")

        return {"raw_emails": raw_emails, "path": str(target)}

    def _load_pst(self, path: Path) -> List[dict[str, Any]]:
        """Run the PST worker script using Python 3.9."""
        cmd = ["py", "-3.9", self.worker_path, "--pst", str(path)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
            emails = []
            for line in result.stdout.splitlines():
                if line.strip():
                    emails.append(json.loads(line))
            return emails
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"PST worker failed: {e.stderr}") from e

    def _load_eml(self, path: Path) -> dict[str, Any]:
        from email.message import EmailMessage
        msg: EmailMessage = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        
        # Basic extraction matching pst_worker output shape
        import base64
        attachments = []
        for part in msg.iter_attachments():
            try:
                name = part.get_filename() or "attachment"
                data = part.get_payload(decode=True) or b""
                attachments.append({
                    "filename": name,
                    "data_b64": base64.b64encode(data).decode("ascii"),
                    "size_bytes": len(data)
                })
            except: continue

        return {
            "subject": str(msg.get("Subject", "")),
            "sender": str(msg.get("From", "")),
            "received": str(msg.get("Date", "")),
            "folder_path": "EML_IMPORT",
            "body_html": self._get_body(msg, "text/html"),
            "body_plain": self._get_body(msg, "text/plain"),
            "attachments": attachments,
            "mail_id": (msg.get("Message-ID") or path.stem).strip("<>")
        }

    def _get_body(self, msg, content_type: str) -> str:
        for part in msg.walk():
            if part.get_content_type() == content_type:
                try: return part.get_content()
                except: pass
        return ""

    def _load_converted_dir(self, path: Path) -> dict[str, Any]:
        """Backward compatibility for already converted email-mcp dirs."""
        meta_path = path / "meta.json"
        body_path = path / "body.md"
        if not meta_path.is_file() or not body_path.is_file():
            raise FileNotFoundError(f"Invalid converted dir: {path}")
        
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = body_path.read_text(encoding="utf-8")
        
        # We wrap the already-markdown body as body_plain and skip HTML
        # The MarkdownConverter should handle this gracefully.
        return {
            "subject": meta.get("subject", ""),
            "sender": meta.get("sender", ""),
            "received": meta.get("received", ""),
            "folder_path": meta.get("folder_path", ""),
            "kind": "email",
            "source": "email_mcp_converted",
            "body_plain": body,
            "body_html": "",
            "attachments": [],
            "mail_id": meta.get("mail_id", "")
        }
