"""File -> raw text loader, exposed as a Haystack @component.

Supports the same formats as the legacy ``scripts.ingest.read_text`` so behavior
is byte-for-byte equivalent: PDF via pypdf, DOCX via python-docx, XLSX via
openpyxl, TXT/MD/CSV via UTF-8 (with chardet fallback). The loader emits a
single ``text`` output plus the resolved source path so downstream components
can build the canonical document_id without re-reading metadata.
"""
from __future__ import annotations

from pathlib import Path

from haystack import component


@component
class LocalFileLoader:
    """Read one local file and return its decoded text, truncated to a max length."""

    def __init__(self, max_chars: int = 2_000_000) -> None:
        self.max_chars = int(max_chars)

    @component.output_types(text=str, path=str, size_bytes=int)
    def run(self, path: str) -> dict:
        target = Path(path).expanduser()
        if not target.is_file():
            raise FileNotFoundError(f"file not found: {target}")
        text = _read_text(target, self.max_chars)
        return {"text": text, "path": str(target), "size_bytes": target.stat().st_size}


def _read_text(path: Path, max_chars: int) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    elif suffix in (".doc", ".docx"):
        from docx import Document

        doc = Document(path)
        text = "\n\n".join(p.text for p in doc.paragraphs if p.text)
    elif suffix in (".xls", ".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        lines: list[str] = []
        for sheet in wb.worksheets:
            lines.append(f"# Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                line = "\t".join(str(cell) if cell is not None else "" for cell in row).strip()
                if line:
                    lines.append(line)
        text = "\n".join(lines)
    else:
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                import chardet

                encoding = chardet.detect(data).get("encoding") or "utf-8"
                text = data.decode(encoding, errors="replace")
            except Exception:
                text = data.decode("utf-8", errors="replace")
    return text[:max_chars]
