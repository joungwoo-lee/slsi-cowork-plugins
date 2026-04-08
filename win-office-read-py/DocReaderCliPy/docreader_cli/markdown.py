from __future__ import annotations


def clean_cell_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", "").replace("\n", " ").strip()


def emit_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    lines: list[str] = []
    for index, row in enumerate(rows):
        cells = [clean_cell_text(cell) for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n".join(lines) + "\n\n"
