#!/usr/bin/env python3

"""
사용 방법:
  1. 로컬에서 게이트웨이 서버를 먼저 실행하여 http://127.0.0.1:18081 로 접속 가능해야 합니다.
  2. Python 3 과 websockets 패키지를 준비합니다.
       설치 예시: python3 -m pip install websockets
  3. 새 세션으로 대화하려면:
       python3 terminal-test.py
  4. 첫 질문을 자동으로 보내려면:
       python3 terminal-test.py --prompt "안녕하세요. 제 이름은 준입니다. 기억해줘."
  5. 여러 질문을 순서대로 자동 전송하려면:
       python3 terminal-test.py --prompt "안녕하세요" --prompt "내 이름이 뭐였지?"
  6. 기존 세션 key 를 재사용하려면:
       python3 terminal-test.py --session-key <key>
  7. 저장된 대화 이력만 보려면:
       python3 terminal-test.py --history-only --session-key <key>

설명:
  - 이 스크립트는 REST API 로 세션을 생성한 뒤 WebSocket 에 연결합니다.
  - 서버가 보내는 user_msg, status, stream, done 이벤트를 그대로 출력합니다.
  - prompt 를 지정하지 않으면 터미널 입력을 받아 한 줄씩 대화합니다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import websockets
except ImportError:  # pragma: no cover - import failure path
    print(
        "websockets 패키지가 필요합니다. 설치 예시: python3 -m pip install websockets",
        file=sys.stderr,
    )
    raise SystemExit(1)


DEFAULT_BASE_URL = "http://127.0.0.1:18081"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenCode cowork gateway 터미널 API 테스트")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="게이트웨이 기본 URL")
    parser.add_argument("--title", default="Python Terminal Test", help="새 세션 제목")
    parser.add_argument(
        "--prompt",
        action="append",
        default=[],
        help="자동으로 전송할 프롬프트. 여러 번 지정 가능",
    )
    parser.add_argument("--session-key", help="기존 세션 key 재사용")
    parser.add_argument(
        "--history-only",
        action="store_true",
        help="세션 이력만 조회하고 WebSocket 연결은 하지 않음",
    )
    return parser.parse_args()


def http_json(method: str, url: str, payload: dict | None = None) -> dict | list:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} 실패: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"게이트웨이에 연결하지 못했습니다: {exc}") from exc


def create_session(base_url: str, title: str) -> str:
    result = http_json("POST", f"{base_url}/api/sessions", {"title": title})
    key = str(result.get("key", "")).strip()
    if not key:
        raise SystemExit(f"세션 key 를 찾지 못했습니다: {result}")
    return key


def load_history(base_url: str, key: str) -> list[dict]:
    result = http_json("GET", f"{base_url}/api/sessions/{key}/history")
    if not isinstance(result, list):
        raise SystemExit(f"이력 응답 형식이 예상과 다릅니다: {result}")
    return result


def print_history(base_url: str, key: str) -> None:
    history = load_history(base_url, key)
    print(f"\n이력 조회 결과: key={key}")
    print(json.dumps(history, ensure_ascii=False, indent=2))


def to_ws_url(base_url: str, key: str) -> str:
    if base_url.startswith("https://"):
        return f"wss://{base_url[len('https://'):].rstrip('/')}/ws/{key}"
    if base_url.startswith("http://"):
        return f"ws://{base_url[len('http://'):].rstrip('/')}/ws/{key}"
    raise SystemExit(f"지원하지 않는 base URL 형식입니다: {base_url}")


def print_event(message: str) -> dict | None:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        print(message)
        return None

    print(json.dumps(data, ensure_ascii=False))
    return data if isinstance(data, dict) else None


async def send_prompt(ws: websockets.ClientConnection, prompt: str) -> None:
    payload = {"action": "send", "prompt": prompt}
    await ws.send(json.dumps(payload, ensure_ascii=False))


async def wait_until_idle(ws: websockets.ClientConnection) -> None:
    while True:
        raw = await ws.recv()
        event = print_event(raw)
        if isinstance(event, dict) and event.get("type") == "status" and event.get("status") == "idle":
            return


async def interactive_chat(ws: websockets.ClientConnection) -> None:
    loop = asyncio.get_running_loop()
    print("\n대화 입력 모드입니다. 빈 줄은 무시되고 Ctrl+C 또는 Ctrl+D 로 종료합니다.")
    while True:
        line = await loop.run_in_executor(None, lambda: input("> "))
        prompt = line.strip()
        if not prompt:
            continue
        await send_prompt(ws, prompt)
        await wait_until_idle(ws)


async def run_chat(base_url: str, key: str, prompts: list[str]) -> None:
    ws_url = to_ws_url(base_url, key)
    print(f"세션 key: {key}")
    print(f"WebSocket URL: {ws_url}")

    async with websockets.connect(ws_url) as ws:
        if prompts:
            for prompt in prompts:
                print(f"\n자동 전송 prompt: {prompt}")
                await send_prompt(ws, prompt)
                await wait_until_idle(ws)
        else:
            await interactive_chat(ws)


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    if args.history_only and not args.session_key:
        raise SystemExit("--history-only 사용 시 --session-key 가 필요합니다.")

    key = args.session_key or create_session(base_url, args.title)
    print(f"사용할 세션 key: {key}")

    if args.history_only:
        print_history(base_url, key)
        return

    try:
        asyncio.run(run_chat(base_url, key, args.prompt))
    except KeyboardInterrupt:
        print("\n사용자에 의해 종료되었습니다.")

    print_history(base_url, key)


if __name__ == "__main__":
    main()
