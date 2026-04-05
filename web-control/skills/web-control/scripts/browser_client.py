#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/tmp/web-control.sock")
    ap.add_argument("--request", required=True, help='JSON string, e.g. {"cmd":"status"}')
    args = ap.parse_args()

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(args.socket)
    s.sendall((json.dumps(json.loads(args.request), ensure_ascii=False) + "\n").encode("utf-8"))

    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()

    line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
    out = json.loads(line) if line else {"ok": False, "reason": "empty_response"}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
