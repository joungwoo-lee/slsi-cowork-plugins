from __future__ import annotations

import os
from typing import Any

from ..markdown import emit_markdown_table
from ..office_app import log, wait_for_active_app, wait_for_matching_document, wait_until_ready
from ..process_watchdog import ProcessWatchdog


DRM_TIMEOUT_SECONDS = 15


def read_word(file_path: str) -> str:
    with ProcessWatchdog("WINWORD") as watchdog:
        app = None
        doc = None
        try:
            log(f"[WordReader] Opening document via shell: {file_path}")
            os.startfile(file_path)
            watchdog.detect_new_process()

            app = wait_for_active_app("Word.Application", watchdog.timeout_ms / 1000)
            try:
                app.Visible = True
            except Exception:
                pass

            doc = wait_for_matching_document(app.Documents, file_path, watchdog.timeout_ms / 1000, "Document")
            try:
                doc.Activate()
            except Exception:
                pass

            wait_until_ready(
                lambda: doc.Content.Text is not None,
                DRM_TIMEOUT_SECONDS,
                "DRM decryption timed out after 15s. The document may require manual DRM authentication.",
            )
            return _extract_content(doc)
        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass


def _extract_content(doc: Any) -> str:
    parts: list[str] = []
    table_ranges: list[tuple[int, int]] = []

    table_count = int(getattr(doc.Tables, "Count", 0))
    for index in range(1, table_count + 1):
        try:
            table = doc.Tables.Item(index)
            table_ranges.append((int(table.Range.Start), int(table.Range.End)))
        except Exception:
            continue

    emitted_table_index = 0
    paragraph_count = int(getattr(doc.Paragraphs, "Count", 0))
    for index in range(1, paragraph_count + 1):
        try:
            paragraph = doc.Paragraphs.Item(index)
            paragraph_range = paragraph.Range
            para_start = int(paragraph_range.Start)

            inside_table = False
            matched_table_index = -1
            for range_index, (start, end) in enumerate(table_ranges):
                if start <= para_start <= end:
                    inside_table = True
                    matched_table_index = range_index
                    break

            if inside_table:
                if matched_table_index == emitted_table_index:
                    parts.append(_emit_table(doc.Tables.Item(emitted_table_index + 1)))
                    emitted_table_index += 1
                continue

            text = (paragraph_range.Text or "").rstrip("\r\n\a").strip()
            if not text:
                continue

            style_name = ""
            try:
                style = paragraph.Style
                style_name = str(getattr(style, "NameLocal", style))
            except Exception:
                pass

            if "Heading 1" in style_name:
                parts.append(f"# {text}\n\n")
            elif "Heading 2" in style_name:
                parts.append(f"## {text}\n\n")
            elif "Heading 3" in style_name:
                parts.append(f"### {text}\n\n")
            elif "Heading" in style_name:
                parts.append(f"#### {text}\n\n")
            else:
                parts.append(f"{text}\n\n")
        except Exception:
            continue

    for index in range(emitted_table_index + 1, table_count + 1):
        try:
            parts.append(_emit_table(doc.Tables.Item(index)))
        except Exception:
            continue

    return "".join(parts)


def _emit_table(table: Any) -> str:
    rows = int(table.Rows.Count)
    cols = int(table.Columns.Count)
    matrix: list[list[str]] = []
    for row in range(1, rows + 1):
        values: list[str] = []
        for col in range(1, cols + 1):
            try:
                cell_text = table.Cell(row, col).Range.Text or ""
                values.append(cell_text.rstrip("\r\n\a\x07"))
            except Exception:
                values.append("")
        matrix.append(values)
    return emit_markdown_table(matrix)
