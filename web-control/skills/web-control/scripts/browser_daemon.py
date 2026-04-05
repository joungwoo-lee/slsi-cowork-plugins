#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


class BrowserDaemon:
    def __init__(self, headed: bool):
        self.headed = headed
        self._lock = threading.Lock()
        self.pw_cm = None
        self.pw = None
        self.context = None
        self.page = None
        self.mode = "headed"
        self.user_data_dir = str(Path.home() / ".cache" / "web-control" / "profile")

    def start(self):
        self.pw_cm = sync_playwright()
        self.pw = self.pw_cm.start()
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        kwargs = {
            "headless": not self.headed,
            "ignore_https_errors": True,
            "executable_path": self.pw.chromium.executable_path,
            "args": ["--no-first-run", "--no-default-browser-check"],
        }
        try:
            self.context = self.pw.chromium.launch_persistent_context(self.user_data_dir, **kwargs)
            self.mode = "headed" if self.headed else "headless"
        except Exception:
            kwargs["headless"] = True
            self.context = self.pw.chromium.launch_persistent_context(self.user_data_dir, **kwargs)
            self.mode = "headless-fallback"
        pages = self.context.pages
        self.page = pages[0] if pages else self.context.new_page()

    def stop(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.pw_cm:
                self.pw_cm.stop()
        except Exception:
            pass

    def _run_actions(self, actions: list, timeout_ms: int) -> tuple[bool, int, list]:
        logs = []
        for i, a in enumerate(actions):
            t = a.get("type")
            sel = a.get("selector")
            try:
                loc = self.page.locator(sel).first
                if t == "click":
                    loc.click(timeout=timeout_ms)
                elif t == "type":
                    loc.fill(a.get("text", ""), timeout=timeout_ms)
                elif t == "press":
                    loc.press(a.get("key", "Enter"), timeout=timeout_ms)
                else:
                    raise ValueError(f"unknown action type: {t}")
                logs.append({"index": i, "ok": True, "type": t, "selector": sel})
            except Exception as e:
                logs.append({"index": i, "ok": False, "type": t, "selector": sel, "error": str(e)})
                return False, i, logs
        return True, -1, logs

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        cmd = req.get("cmd")
        timeout_ms = int(req.get("timeout_ms", 30000))
        with self._lock:
            try:
                if cmd == "status":
                    return {
                        "ok": True,
                        "mode": self.mode,
                        "url": self.page.url,
                        "title": self.page.title(),
                    }

                if cmd == "open":
                    resp = self.page.goto(req["url"], wait_until="domcontentloaded", timeout=timeout_ms)
                    return {
                        "ok": True,
                        "url": self.page.url,
                        "title": self.page.title(),
                        "status": resp.status if resp else None,
                    }

                if cmd == "act":
                    if url := req.get("url"):
                        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    ok, failed_idx, logs = self._run_actions(req.get("actions", []), timeout_ms)
                    result: dict[str, Any] = {"ok": ok, "logs": logs, "url": self.page.url}
                    if not ok:
                        result["failed_index"] = failed_idx
                    return result

                if cmd == "flow":
                    steps: list = []
                    if url := req.get("url"):
                        resp = self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        steps.append({"step": "open", "url": self.page.url, "status": resp.status if resp else None})
                    if actions := req.get("actions"):
                        ok, failed_idx, logs = self._run_actions(actions, timeout_ms)
                        steps.append({"step": "act", "logs": logs})
                        if not ok:
                            return {"ok": False, "failed_index": failed_idx, "steps": steps, "url": self.page.url}
                    if sel := req.get("wait_selector"):
                        self.page.locator(sel).first.wait_for(timeout=timeout_ms)
                        steps.append({"step": "wait_selector", "selector": sel})
                    if text := req.get("wait_text"):
                        self.page.get_by_text(text).first.wait_for(timeout=timeout_ms)
                        steps.append({"step": "wait_text", "text": text})
                    if filename := req.get("filename"):
                        img = _save_screenshot(self.page, filename, bool(req.get("full_page", False)))
                        steps.append({"step": "screenshot", "image": img})
                    return {"ok": True, "steps": steps, "url": self.page.url}

                if cmd == "snapshot":
                    if url := req.get("url"):
                        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    items = self.page.evaluate("""() => {
                        const els = Array.from(document.querySelectorAll(
                            'a[href],button,input,textarea,select,[role="button"],[role="link"],[role="menuitem"],[role="checkbox"],[role="radio"],[role="tab"]'
                        )).filter(el => {
                            const r = el.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        });
                        return els.slice(0, 80).map((el, i) => ({
                            idx: i,
                            tag: el.tagName.toLowerCase(),
                            id: el.id || null,
                            name: el.getAttribute('name'),
                            type: el.getAttribute('type'),
                            role: el.getAttribute('role'),
                            text: (el.innerText || el.value || '').trim().slice(0, 100),
                            testid: el.getAttribute('data-testid'),
                        }));
                    }""")
                    return {"ok": True, "url": self.page.url, "count": len(items), "items": items}

                if cmd == "wait":
                    if url := req.get("url"):
                        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if sel := req.get("selector"):
                        self.page.locator(sel).first.wait_for(timeout=timeout_ms)
                    if text := req.get("text"):
                        self.page.get_by_text(text).first.wait_for(timeout=timeout_ms)
                    return {"ok": True, "url": self.page.url}

                if cmd == "screenshot":
                    if not (filename := req.get("filename")):
                        return {"ok": False, "reason": "filename_required"}
                    if url := req.get("url"):
                        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    img = _save_screenshot(self.page, filename, bool(req.get("full_page", False)))
                    return {"ok": True, "url": self.page.url, "image": img}

                if cmd == "close":
                    return {"ok": True, "closing": True}

                return {"ok": False, "reason": "unknown_cmd", "cmd": cmd}

            except Exception as e:
                return {"ok": False, "reason": "exception", "error": str(e), "cmd": cmd}


def _save_screenshot(page: Any, filename: str, full_page: bool) -> str:
    filename = Path(filename).name or "page.png"
    out_dir = Path("outputs/browser")
    out_dir.mkdir(parents=True, exist_ok=True)
    img = out_dir / filename
    page.screenshot(path=str(img), full_page=full_page)
    return str(img.resolve())


def _serve_conn(conn: socket.socket, daemon: BrowserDaemon, stop: threading.Event) -> None:
    with conn:
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return
            data += chunk
        line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
        if not line:
            return
        out = daemon.handle(json.loads(line))
        conn.sendall((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
        if out.get("closing"):
            stop.set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/tmp/web-control.sock")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    try:
        os.unlink(args.socket)
    except FileNotFoundError:
        pass

    daemon = BrowserDaemon(headed=not args.headless)
    daemon.start()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(args.socket)
    os.chmod(args.socket, 0o600)
    server.listen(16)
    server.settimeout(1.0)
    print(json.dumps({"ok": True, "socket": args.socket, "mode": daemon.mode}), flush=True)

    stop = threading.Event()
    try:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            _serve_conn(conn, daemon, stop)
    finally:
        daemon.stop()
        try:
            os.unlink(args.socket)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
