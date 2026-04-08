from __future__ import annotations

import argparse
import os
import platform
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="DocReaderCli",
        description="Read DRM-protected Office documents through Windows COM automation.",
    )
    parser.add_argument("--file", dest="file_path", help="Absolute path to the Office document")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    file_path = args.file_path
    if not file_path:
        print("Usage: DocReaderCli --file <path>", file=sys.stderr)
        print(
            "Supported formats: .docx, .doc, .pdf, .xlsx, .xls, .pptx, .ppt, .pptm, .ppsx, .pps, .potx, .potm",
            file=sys.stderr,
        )
        return 1

    if platform.system() != "Windows":
        print("Error: This tool only runs on Windows with Microsoft Office installed.", file=sys.stderr)
        return 99

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 2

    ext = os.path.splitext(file_path)[1].lower()

    try:
        import pythoncom
        from .readers.excel_reader import read_excel
        from .readers.powerpoint_reader import read_powerpoint
        from .readers.word_reader import read_word

        pythoncom.CoInitialize()
        try:
            if ext in {".docx", ".doc", ".pdf"}:
                result = read_word(file_path)
            elif ext in {".xlsx", ".xls"}:
                result = read_excel(file_path)
            elif ext in {".pptx", ".ppt", ".pptm", ".ppsx", ".pps", ".potx", ".potm"}:
                result = read_powerpoint(file_path)
            else:
                raise NotImplementedError(f"Unsupported file extension: {ext}")
        finally:
            pythoncom.CoUninitialize()

        sys.stdout.write(result)
        return 0
    except TimeoutError as exc:
        print(f"Timeout: {exc}", file=sys.stderr)
        return 3
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Fatal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 99
