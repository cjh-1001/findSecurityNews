from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RATE_LIMIT_CODE = 11232
DEFAULT_RETRY_DELAYS = (30, 60)


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _read_json_response(request: Request) -> dict:
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Feishu webhook HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Feishu webhook network error: {exc.reason}") from exc

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Feishu webhook invalid JSON response: {body}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"Feishu webhook unexpected response: {body}")
    return result


def _build_text_request(webhook: str, text: str, secret: str = "") -> Request:
    payload: dict = {
        "msg_type": "text",
        "content": {"text": text},
    }
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _sign(secret, timestamp)

    return Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )


def send_text(
    webhook: str,
    text: str,
    secret: str = "",
    retry_delays: tuple[int, ...] = DEFAULT_RETRY_DELAYS,
) -> dict:
    for attempt in range(len(retry_delays) + 1):
        request = _build_text_request(webhook, text, secret)
        result = _read_json_response(request)
        code = result.get("code", 0)
        if code in (0, None):
            return result

        msg = result.get("msg", "")
        if code == RATE_LIMIT_CODE and attempt < len(retry_delays):
            delay = retry_delays[attempt]
            print(
                f"Feishu webhook frequency limited (code={code}); retrying in {delay}s.",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue

        raise RuntimeError(f"Feishu webhook error {code}: {msg}")


def truncate(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
