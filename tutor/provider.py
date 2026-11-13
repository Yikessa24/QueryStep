"""Minimal OpenAI-compatible transport shared by the tutor and its probe."""

from contextlib import contextmanager
from contextvars import ContextVar
from ipaddress import ip_address

import httpx


_meter: ContextVar[list[dict] | None] = ContextVar("provider_meter", default=None)


@contextmanager
def measure_calls():
    calls: list[dict] = []
    token = _meter.set(calls)
    try:
        yield calls
    finally:
        _meter.reset(token)


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class ChatModel:
    def __init__(self, base_url: str, model: str, api_key: str | None, *,
                 allow_insecure_http: bool = False,
                 transport: httpx.BaseTransport | None = None):
        try:
            url = httpx.URL(base_url.strip())
        except httpx.InvalidURL as error:
            raise ValueError("Invalid model service URL.") from error
        if (url.scheme not in {"http", "https"} or not url.host or url.userinfo
                or url.query or url.fragment):
            raise ValueError("Use an HTTP(S) base URL without credentials, query, or fragment.")
        if (url.scheme == "http" and not allow_insecure_http
                and (api_key or not _loopback(url.host))):
            raise ValueError("An authenticated or remote model service requires HTTPS by default.")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(
            base_url=str(url).rstrip("/") + "/", headers=headers, trust_env=False,
            follow_redirects=False, transport=transport,
        )
        self.model = model

    def list_models(self, timeout: float = 8) -> list[str]:
        response = self.client.get("models", timeout=timeout)
        response.raise_for_status()
        rows = response.json()["data"]
        return sorted({row["id"] for row in rows if isinstance(row.get("id"), str)})

    def reply(self, messages: list[dict], tools: list[dict], timeout: float, *,
              tool_choice: dict | None = None, response_format: dict | None = None) -> dict:
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": 150}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format
        calls = _meter.get()
        record = {}
        if calls is not None:
            calls.append(record)
        response = self.client.post("chat/completions", json=body, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if calls is not None and isinstance(payload.get("usage"), dict):
            record.update({name: count for name, count in payload["usage"].items()
                           if name in {"prompt_tokens", "completion_tokens", "total_tokens"}
                           and type(count) is int and count >= 0})
        message = payload["choices"][0]["message"]
        if not isinstance(message, dict):
            raise ValueError("Model response did not contain a message object.")
        return message

    def close(self):
        self.client.close()
