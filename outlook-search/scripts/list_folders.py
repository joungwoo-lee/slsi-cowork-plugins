"""List all Outlook stores (accounts) and their folder tree as JSON."""
from __future__ import annotations

import json
import sys

try:
    import win32com.client
except ImportError:
    sys.stderr.write("ERROR: pywin32 not installed. Run: pip install pywin32\n")
    sys.exit(2)


def walk(folder, depth: int = 0, max_depth: int = 6):
    if depth > max_depth:
        return None
    children = []
    try:
        for sub in folder.Folders:
            node = walk(sub, depth + 1, max_depth)
            if node is not None:
                children.append(node)
    except Exception:
        pass
    try:
        item_count = folder.Items.Count
    except Exception:
        item_count = -1
    return {
        "name": folder.Name,
        "item_count": item_count,
        "children": children,
    }


def main():
    app = win32com.client.Dispatch("Outlook.Application")
    ns = app.GetNamespace("MAPI")

    out = []
    for store in ns.Stores:
        try:
            root = store.GetRootFolder()
        except Exception:
            continue
        out.append({
            "account": store.DisplayName,
            "path": store.FilePath if hasattr(store, "FilePath") else None,
            "root": walk(root),
        })

    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
