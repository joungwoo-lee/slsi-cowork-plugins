import sys
import json
import logging
from pathlib import Path
from typing import Iterator, Any

# This script must be run with Python 3.9 due to pypff dependency.
if sys.version_info[:2] != (3, 9):
    print(f"ERROR: pst_worker.py requires Python 3.9, got {sys.version_info.major}.{sys.version_info.minor}", file=sys.stderr)
    sys.exit(1)

import pypff

def _safe_str(value) -> str:
    if value is None: return ""
    if isinstance(value, bytes):
        for enc in ("utf-8", "cp1252", "cp949", "latin-1"):
            try: return value.decode(enc)
            except: continue
        return value.decode("utf-8", errors="replace")
    return str(value)

def _resolve_attachment_name(att, idx: int) -> str:
    for attr in ("long_filename", "get_long_filename", "filename", "get_filename", "name", "get_name"):
        if hasattr(att, attr):
            v = getattr(att, attr)
            if callable(v):
                try: v = v()
                except: continue
            s = _safe_str(v).strip()
            if s: return s
    return f"attachment_{idx}"

def _extract_attachments(message):
    out = []
    try: count = message.get_number_of_attachments()
    except: return out
    for i in range(count):
        try:
            att = message.get_attachment(i)
            name = _resolve_attachment_name(att, i)
            size = att.get_size() if hasattr(att, "get_size") else 0
            data = att.read_buffer(size) if size and hasattr(att, "read_buffer") else b""
            # We return base64 for binary data in JSON
            import base64
            out.append({
                "filename": name,
                "data_b64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data)
            })
        except: continue
    return out

def _walk_folder(folder, path: str):
    name = _safe_str(getattr(folder, "name", "")) or "(root)"
    here = f"{path}/{name}" if path else name
    try:
        for i in range(folder.get_number_of_sub_messages()):
            msg = folder.get_sub_message(i)
            yield here, msg
    except: pass
    try:
        for i in range(folder.get_number_of_sub_folders()):
            yield from _walk_folder(folder.get_sub_folder(i), here)
    except: pass

def run_worker(pst_path: str, limit: int = None):
    pst = pypff.file()
    pst.open(pst_path)
    count = 0
    try:
        root = pst.get_root_folder()
        for folder_path, msg in _walk_folder(root, ""):
            try:
                data = {
                    "subject": _safe_str(msg.get_subject()),
                    "sender": _safe_str(msg.get_sender_name()),
                    "received": _safe_str(msg.get_delivery_time()),
                    "folder_path": folder_path,
                    "body_html": _safe_str(getattr(msg, "html_body", None) or msg.get_html_body()),
                    "body_plain": _safe_str(getattr(msg, "plain_text_body", None) or msg.get_plain_text_body()),
                    "attachments": _extract_attachments(msg)
                }
                print(json.dumps(data, ensure_ascii=False))
                count += 1
                if limit and count >= limit: break
            except: continue
    finally:
        pst.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pst", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run_worker(args.pst, args.limit)
