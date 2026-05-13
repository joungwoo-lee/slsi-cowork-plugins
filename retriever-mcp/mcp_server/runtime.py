"""Runtime utilities used by tool handlers."""
from __future__ import annotations

import contextlib
import json
import sys
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode

from . import bootstrap


def log(msg: str) -> None:
    """Emit a log line to stderr. NEVER use print() to stdout — it would corrupt JSON-RPC."""
    print(f"[retriever-mcp] {msg}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def silenced_stdout():
    """Redirect stdout to stderr while a tool runs.

    The JSON-RPC stream lives on stdout. A stray print() from any library
    inside a tool call would inject garbage into the wire format and the
    client would disconnect. We route stdout writes to stderr (where they
    become visible logs) for the duration of the call.
    """
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = saved


class RetrieverHttpError(Exception):
    def __init__(self, status: int | None, message: str, body: Any | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _auth_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if bootstrap.API_KEY:
        headers["Authorization"] = f"Bearer {bootstrap.API_KEY}"
    return headers


def _build_url(path: str, query: dict[str, Any] | None = None) -> str:
    url = f"{bootstrap.BASE_URL}{path}"
    if query:
        filtered = {k: v for k, v in query.items() if v is not None}
        if filtered:
            url = f"{url}?{urlencode(filtered, doseq=True)}"
    return url


def _read_response(resp) -> Any:
    raw = resp.read()
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw.decode("utf-8", errors="replace")


def http_request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    json_body: Any | None = None,
    form: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: float | None = None,
) -> Any:
    """Make an HTTP request to the retriever API and return parsed JSON.

    Uses urllib only (stdlib) to keep the MCP dependency-free aside from the
    one we already need for multipart upload (`requests`, see handlers).
    """
    url = _build_url(path, query)
    headers = _auth_headers()
    if extra_headers:
        headers.update(extra_headers)

    body: bytes | None = None
    if raw_body is not None:
        body = raw_body
        if content_type:
            headers["Content-Type"] = content_type
    elif json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        body = urlencode({k: v for k, v in form.items() if v is not None}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib_request.Request(url, data=body, headers=headers, method=method.upper())
    effective_timeout = timeout if timeout is not None else bootstrap.REQUEST_TIMEOUT
    try:
        with urllib_request.urlopen(req, timeout=effective_timeout) as resp:
            return _read_response(resp)
    except urllib_error.HTTPError as exc:
        payload = None
        try:
            payload = _read_response(exc)
        except Exception:
            pass
        raise RetrieverHttpError(exc.code, f"HTTP {exc.code} from {url}", payload) from exc
    except urllib_error.URLError as exc:
        raise RetrieverHttpError(
            None,
            f"connection failed for {url}: {exc.reason}. "
            f"Is retriever_engine running at {bootstrap.BASE_URL}?",
        ) from exc
