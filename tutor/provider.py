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
        self._async_client = None

    def list_models(self, timeout: float = 8) -> list[str]:
        response = self.client.get("models", timeout=timeout)
        response.raise_for_status()
        rows = response.json()["data"]
        return sorted({row["id"] for row in rows if isinstance(row.get("id"), str)})

    def reply(self, messages: list[dict], tools: list[dict], timeout: float, *,
              tool_choice: dict | None = None, response_format: dict | None = None) -> dict:
        body = self._request_body(messages)
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format
        record = self._start_call()
        response = self.client.post("chat/completions", json=body, timeout=timeout)
        return self._read_message(response, record)

    def _request_body(self, messages, *, model=None, max_tokens=150):
        return {"model": model or self.model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}

    async def reply_json(self, messages: list[dict], timeout: float, *, model: str, max_tokens: int = 256) -> dict:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                base_url=self.client.base_url, headers=self.client.headers, trust_env=False, follow_redirects=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            )
        body = self._request_body(messages, model=model, max_tokens=max_tokens)
        body["response_format"] = {"type": "json_object"}
        record = self._start_call()
        response = await self._async_client.post("chat/completions", json=body, timeout=timeout)
        return self._read_message(response, record)

    @staticmethod
    def _start_call():
        calls = _meter.get()
        if calls is not None:
            record = {}
            calls.append(record)
            return record
        return None

    @staticmethod
    def _read_message(response, record):
        response.raise_for_status()
        payload = response.json()
        if record is not None and isinstance(payload.get("usage"), dict):
            record.update({name: count for name, count in payload["usage"].items()
                           if name in {"prompt_tokens", "completion_tokens", "total_tokens"}
                           and type(count) is int and count >= 0})
        message = payload["choices"][0]["message"]
        if not isinstance(message, dict):
            raise ValueError("Model response did not contain a message object.")
        return message

    def close(self):
        self.client.close()

    async def aclose(self):
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
