from __future__ import annotations

import os
from typing import Any

from ..markdown import emit_markdown_table
from ..office_app import log, wait_for_active_app, wait_for_matching_document, wait_until_ready
from ..process_watchdog import ProcessWatchdog


DRM_TIMEOUT_SECONDS = 15
MSO_TRUE = -1


def read_powerpoint(file_path: str) -> str:
    with ProcessWatchdog("POWERPNT") as watchdog:
        app = None
        presentation = None
        try:
            log(f"[PPTReader] Opening presentation via shell: {file_path}")
            os.startfile(file_path)
            watchdog.detect_new_process()

            app = wait_for_active_app("PowerPoint.Application", watchdog.timeout_ms / 1000)
            presentation = wait_for_matching_document(
                app.Presentations,
                file_path,
                watchdog.timeout_ms / 1000,
                "Presentation",
            )

            wait_until_ready(
                lambda: _is_powerpoint_ready(presentation),
                DRM_TIMEOUT_SECONDS,
                "DRM decryption timed out after 15s.",
            )
            return _extract_presentation(presentation)
        finally:
            if presentation is not None:
                try:
                    presentation.Close()
                except Exception:
                    pass


def _is_powerpoint_ready(presentation: Any) -> bool:
    if int(presentation.Slides.Count) == 0:
        return True
    first_slide = presentation.Slides.Item(1)
    _ = first_slide.Shapes.Count
    return True


def _extract_presentation(presentation: Any) -> str:
    parts: list[str] = []
    slide_count = int(presentation.Slides.Count)
    for index in range(1, slide_count + 1):
        try:
            slide = presentation.Slides.Item(index)
            parts.append(_extract_slide(slide, index))
        except Exception as exc:
            log(f"[PPTReader] Error on slide {index}: {exc}")
    return "".join(parts)


def _extract_slide(slide: Any, slide_number: int) -> str:
    parts = [f"## Slide {slide_number}\n\n"]
    title_name = None

    try:
        if slide.Shapes.HasTitle == MSO_TRUE:
            title_shape = slide.Shapes.Title
            title_name = title_shape.Name
            title_text = title_shape.TextFrame.TextRange.Text
            if title_text and str(title_text).strip():
                parts.append(f"### {str(title_text).strip()}\n\n")
    except Exception:
        pass

    shape_count = int(slide.Shapes.Count)
    for index in range(1, shape_count + 1):
        try:
            shape = slide.Shapes.Item(index)
            if title_name and getattr(shape, "Name", None) == title_name:
                continue

            if getattr(shape, "HasTextFrame", 0) == MSO_TRUE:
                text = shape.TextFrame.TextRange.Text
                if text and str(text).strip():
                    parts.append(f"{str(text).strip()}\n\n")

            if getattr(shape, "HasTable", 0) == MSO_TRUE:
                parts.append(_extract_table(shape.Table))
        except Exception:
            continue

    try:
        note_shapes = slide.NotesPage.Shapes
        note_count = int(note_shapes.Count)
        for index in range(1, note_count + 1):
            try:
                note_shape = note_shapes.Item(index)
                if getattr(note_shape, "HasTextFrame", 0) == MSO_TRUE:
                    note_text = note_shape.TextFrame.TextRange.Text
                    if note_text and len(str(note_text).strip()) > 1:
                        parts.append(f"> **Note:** {str(note_text).strip()}\n\n")
            except Exception:
                continue
    except Exception:
        pass

    return "".join(parts)


def _extract_table(table: Any) -> str:
    rows = int(table.Rows.Count)
    cols = int(table.Columns.Count)
    matrix: list[list[str]] = []
    for row in range(1, rows + 1):
        values: list[str] = []
        for col in range(1, cols + 1):
            try:
                values.append(str(table.Cell(row, col).Shape.TextFrame.TextRange.Text or ""))
            except Exception:
                values.append("")
        matrix.append(values)
    return emit_markdown_table(matrix)
