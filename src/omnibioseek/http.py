"""Small retrying HTTP client with injectable transport for deterministic tests."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpError(RuntimeError):
    """HTTP request failed after retries."""


@dataclass(slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]
    url: str

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


Transport = Callable[[str, Mapping[str, str]], HttpResponse]


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str = "OmniBioSeek/0.1",
        retries: int = 3,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 45.0,
        transport: Transport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @staticmethod
    def with_query(url: str, params: Mapping[str, str | int | None]) -> str:
        encoded = urlencode({key: value for key, value in params.items() if value is not None})
        return f"{url}{'&' if '?' in url else '?'}{encoded}" if encoded else url

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        target = self.with_query(url, params or {})
        request_headers = {"User-Agent": self.user_agent, **dict(headers or {})}
        if self.transport:
            return self.transport(target, request_headers)

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = Request(target, headers=request_headers)
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    return HttpResponse(
                        status=response.status,
                        body=response.read(),
                        headers=dict(response.headers.items()),
                        url=response.url,
                    )
            except HTTPError as exc:
                last_error = exc
                if exc.code < 500 and exc.code != 429:
                    break
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise HttpError(f"GET {target} failed: {last_error}") from last_error

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.get(url, **kwargs).text()

