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
        elif target.is_dir():
            raw_emails = [self._load_converted_dir(target)]
        else:
            raise FileNotFoundError(f"Email source must be a .pst file or a converted directory; got: {target}")

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
