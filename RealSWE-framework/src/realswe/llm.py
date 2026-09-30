from __future__ import annotations

import random
import threading
import time
from typing import Any

from openai import APIError, OpenAI, RateLimitError
from pydantic import BaseModel


_thread_local = threading.local()
_client_kwargs: dict[str, Any] = {}


def configure_client(*, base_url: str | None, api_key: str | None) -> None:
    global _client_kwargs
    _client_kwargs = {}
    if base_url:
        _client_kwargs["base_url"] = base_url
    if api_key:
        _client_kwargs["api_key"] = api_key
    if hasattr(_thread_local, "client"):
        delattr(_thread_local, "client")


def _client() -> OpenAI:
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = OpenAI(max_retries=0, **_client_kwargs)
        _thread_local.client = client
    return client


def _usage(value: Any) -> dict[str, int | None]:
    if value is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": None,
            "total_tokens": 0,
        }
    details = getattr(value, "completion_tokens_details", None)
    return {
        "prompt_tokens": value.prompt_tokens,
        "completion_tokens": value.completion_tokens,
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        "total_tokens": value.total_tokens,
    }


def call_structured(
    *,
    messages: list[dict[str, str]],
    schema: type[BaseModel],
    model: str,
    reasoning_effort: str,
    max_retries: int,
) -> tuple[BaseModel, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        started = time.perf_counter()
        try:
            response = _client().chat.completions.parse(
                model=model,
                messages=messages,
                reasoning_effort=reasoning_effort,
                response_format=schema,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError(
                    "model returned no parsed response "
                    f"(finish_reason={response.choices[0].finish_reason})"
                )
            return parsed, {
                "model": getattr(response, "model", None),
                "response_id": getattr(response, "id", None),
                "usage": _usage(response.usage),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        except (RateLimitError, APIError) as exc:
            last_error = exc
            status = getattr(exc, "status_code", None)
            permanent = status is not None and 400 <= status < 500 and status not in (408, 409, 429)
            if attempt == max_retries or permanent:
                break
            response = getattr(exc, "response", None)
            retry_after = None
            if response is not None:
                try:
                    retry_after = float(response.headers.get("retry-after"))
                except (AttributeError, TypeError, ValueError):
                    retry_after = None
            delay = retry_after if retry_after is not None else 2 ** attempt
            time.sleep(min(delay, 60.0) + random.uniform(0.0, 0.5))
    assert last_error is not None
    raise last_error
