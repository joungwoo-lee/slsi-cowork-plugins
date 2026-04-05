---
name: web-control
description: Persistent browser control using a Playwright daemon. Use when the user wants to open a visible browser, keep it open, and send follow-up commands to the same session; auto-falls back to headless if GUI is unavailable.
---

# Web Control (Persistent Browser)

## Goal
One browser session stays alive. All commands route to the same tab.

Scripts are in the `scripts/` folder next to this file.
Derive `<SCRIPTS_DIR>` from this file's location — no `find`, no env var discovery.

## Start daemon (once per session)
```bash
DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 \
  python3 <SCRIPTS_DIR>/browser_daemon.py --socket /tmp/web-control.sock &
```
Daemon prints `{"ok": true, "mode": "headed"|"headless-fallback"}` when ready.
Profile: `~/.cache/web-control/profile` — logins persist across restarts.

## Commands

Status:
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"status"}'
```

Open page:
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"open","url":"https://example.com"}'
```

Act (click / type / press):
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"act","actions":[{"type":"click","selector":"text=Login"}]}'
```

Flow — open + act + wait in one round-trip (use this to minimize approvals):
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"flow","url":"https://example.com","actions":[{"type":"type","selector":"input[name=q]","text":"hello"}],"wait_text":"results"}'
```

DOM snapshot (visible interactive elements only):
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"snapshot"}'
```

Screenshot (only when explicitly requested):
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"screenshot","filename":"page.png","full_page":true}'
```

Close:
```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"close"}'
```

## Output
Screenshots saved to `outputs/browser/<filename>`.

## Rules
- Default: DOM-based commands (open / act / flow / snapshot). Screenshot only on explicit request.
- Use `flow` to bundle open + act + wait into one call — fewer round-trips, fewer approvals.

---

## 실전 예시: Google 페이지 열고 클릭하기

### 1. 설치된 Playwright 및 Chromium 확인

```bash
# Playwright 설치 경로 확인
python3 -c "import playwright; print(playwright.__file__)"

# 내장 Chromium 실행 파일 확인
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
"
```

### 2. 데몬이 실행 중인지 먼저 확인

```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"status"}' 2>/dev/null || echo "daemon_not_running"
```

응답이 없으면 `daemon_not_running` 출력 → 3번으로 진행.

### 3. 데몬 시작 (세션당 한 번)

```bash
DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 \
  python3 <SCRIPTS_DIR>/browser_daemon.py --socket /tmp/web-control.sock &
sleep 4
```

성공 시 출력: `{"ok": true, "socket": "/tmp/web-control.sock", "mode": "headed"}`

### 4. Google 페이지 열기

```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"open","url":"https://www.google.com"}'
```

출력 예:
```json
{"ok": true, "url": "https://www.google.com/", "title": "Google", "status": 200}
```

### 5. DOM 스냅샷으로 클릭 가능한 요소 파악

```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"snapshot"}'
```

출력 예 (일부):
```json
{
  "ok": true,
  "url": "https://www.google.com/",
  "count": 19,
  "items": [
    {"idx": 0, "tag": "a", "text": "Google 정보"},
    {"idx": 3, "tag": "a", "text": "이미지"},
    {"idx": 10, "tag": "input", "name": "btnK", "text": "Google 검색"},
    ...
  ]
}
```

→ `text=` 셀렉터로 클릭할 요소를 특정한다.

### 6. 임의 클릭 1 — "이미지" 링크

```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"act","actions":[{"type":"click","selector":"text=이미지"}]}'
```

출력 예:
```json
{"ok": true, "logs": [{"index": 0, "ok": true, "type": "click", "selector": "text=이미지"}], "url": "https://www.google.com/imghp?hl=ko&ogbl"}
```

### 7. 임의 클릭 2 — "Google 정보" 링크

```bash
python3 <SCRIPTS_DIR>/browser_client.py --socket /tmp/web-control.sock \
  --request '{"cmd":"act","actions":[{"type":"click","selector":"text=Google 정보"}]}'
```

출력 예:
```json
{"ok": true, "logs": [{"index": 0, "ok": true, "type": "click", "selector": "text=Google 정보"}], "url": "https://about.google/..."}
```
