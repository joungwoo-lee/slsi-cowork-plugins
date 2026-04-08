from __future__ import annotations

import os
import subprocess
from typing import Any

from ..markdown import clean_cell_text, emit_markdown_table
from ..office_app import log, wait_for_active_app, wait_for_matching_document, wait_until_ready
from ..process_watchdog import ProcessWatchdog


DRM_TIMEOUT_SECONDS = 15


def read_excel(file_path: str) -> str:
    with ProcessWatchdog("EXCEL") as watchdog:
        app = None
        workbook = None
        try:
            _start_excel_read_only(file_path)
            watchdog.detect_new_process()

            app = wait_for_active_app("Excel.Application", watchdog.timeout_ms / 1000)
            app.DisplayAlerts = False
            app.Visible = True

            workbook = wait_for_matching_document(app.Workbooks, file_path, watchdog.timeout_ms / 1000, "Workbook")
            try:
                workbook.Activate()
            except Exception:
                pass

            wait_until_ready(
                lambda: _is_excel_ready(workbook),
                DRM_TIMEOUT_SECONDS,
                "DRM decryption timed out after 15s.",
            )
            return _extract_workbook(workbook)
        finally:
            if workbook is not None:
                try:
                    workbook.Close(False)
                except Exception:
                    pass


def _start_excel_read_only(file_path: str) -> None:
    log(f"[ExcelReader] Opening workbook in read-only Excel: {file_path}")
    try:
        subprocess.Popen(["excel.exe", "/r", file_path])
    except Exception:
        os.startfile(file_path)


def _is_excel_ready(workbook: Any) -> bool:
    worksheets = workbook.Worksheets
    if int(worksheets.Count) <= 0:
        return False
    first_sheet = worksheets.Item(1)
    used_range = first_sheet.UsedRange
    _ = used_range.Rows.Count
    return True


def _extract_workbook(workbook: Any) -> str:
    parts: list[str] = []
    worksheets = workbook.Worksheets
    sheet_count = int(worksheets.Count)
    for index in range(1, sheet_count + 1):
        try:
            sheet = worksheets.Item(index)
            parts.append(_extract_sheet(sheet))
        except Exception as exc:
            log(f"[ExcelReader] Error reading sheet #{index}: {exc}")
    return "".join(parts)


def _extract_sheet(sheet: Any) -> str:
    used_range = sheet.UsedRange
    row_count = int(used_range.Rows.Count)
    col_count = int(used_range.Columns.Count)
    if row_count <= 0 or col_count <= 0:
        return f"## Sheet: {sheet.Name}\n\n"

    matrix: list[list[str]] = []
    for row in range(1, row_count + 1):
        values: list[str] = []
        for col in range(1, col_count + 1):
            try:
                values.append(clean_cell_text(used_range.Cells(row, col).Text))
            except Exception:
                values.append("")
        matrix.append(values)

    return f"## Sheet: {sheet.Name}\n\n" + emit_markdown_table(matrix)
