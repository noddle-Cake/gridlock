"""Thin Gemini wrapper behind a protocol so services can be tested without the API."""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import get_settings


class LLMUnavailableError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    name: str
    result: str  # JSON text handed back to the model
    is_error: bool = False


@dataclass
class AgentTurn:
    """One model response in a tool-calling conversation: tools to run, or the answer."""

    calls: list[ToolCall]
    text: str
    handle: str | None = None  # continues the conversation (a Gemini interaction id)


class LLMClient(Protocol):
    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str: ...

    async def generate_text(self, prompt: str) -> str: ...

    async def converse(
        self, *, system: str, tools: list[dict[str, Any]], message: str | None = None,
        results: list[ToolResult] | None = None, previous: str | None = None,
    ) -> AgentTurn:
        """Start a conversation with `message`, or continue `previous` with tool results."""
        ...


class DailyQuotaExhaustedError(LLMUnavailableError):
    pass


def _status(exc: BaseException) -> int | None:
    """HTTP status of an API error: `code` on generate_content errors, `status_code` on
    Interactions API errors."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _error_text(exc: BaseException) -> str:
    body = getattr(exc, "body", None)
    return f"{exc} {body}" if isinstance(body, str) else str(exc)


def is_daily_quota(exc: BaseException) -> bool:
    """A 429 against a per-day quota: retrying cannot help until the quota resets,
    although the response still carries a short retry hint."""
    return _status(exc) == 429 and "PerDay" in _error_text(exc)


def is_transient(exc: BaseException) -> bool:
    """Per-minute rate limits (429) and server-side failures (5xx) are worth retrying."""
    code = _status(exc)
    if is_daily_quota(exc):
        return False
    return isinstance(code, int) and (code == 429 or code >= 500)


def retry_after(exc: BaseException) -> float | None:
    """Seconds the API asked us to wait (429 RetryInfo "retryDelay": "40s"), if any."""
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        for item in (details.get("error") or {}).get("details") or []:
            delay = item.get("retryDelay") if isinstance(item, dict) else None
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    pass
    m = re.search(r"retry in ([\d.]+)s", _error_text(exc))
    return float(m.group(1)) if m else None


async def with_retries(call, *, attempts: int, base_delay: float = 5.0):
    """Await `call()`, retrying transient errors with jittered exponential backoff,
    waiting at least as long as the server's retry hint."""
    for attempt in range(attempts):
        try:
            return await call()
        except Exception as exc:
            if attempt + 1 >= attempts or not is_transient(exc):
                raise
            delay = base_delay * 2**attempt * (0.75 + random.random() / 2)
            hint = retry_after(exc)
            await asyncio.sleep(max(delay, hint + 1) if hint is not None else delay)
    raise AssertionError("unreachable")


class RequestPacer:
    """Spaces request starts to stay under a requests-per-minute quota.

    One pacer per client, and the app shares one client, so concurrent uploads and
    brief generation all draw from the same budget (free tier: 5/min per model).
    """

    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


class GeminiClient:
    def __init__(
        self, api_key: str, model: str, *, max_attempts: int = 6, requests_per_minute: int = 0
    ) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._attempts = max_attempts
        self._pacer = RequestPacer(requests_per_minute)

    async def _paced(self, request):
        async def call():
            await self._pacer.wait()  # every attempt, retries included, spends quota
            return await request()

        try:
            return await with_retries(call, attempts=self._attempts)
        except Exception as exc:
            if is_daily_quota(exc):
                raise DailyQuotaExhaustedError(
                    f"Gemini daily request quota for {self._model} is used up; it resets at "
                    "midnight US Pacific. Retry then, switch GEMINI_MODEL, or enable billing."
                ) from exc
            raise

    async def _generate(self, prompt: str, config: Any) -> str:
        response = await self._paced(
            lambda: self._client.aio.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
        )
        if not response.text:
            raise LLMUnavailableError("Gemini returned an empty response")
        return response.text

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        from google.genai import types

        return await self._generate(prompt, types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.0,
        ))

    async def generate_text(self, prompt: str) -> str:
        from google.genai import types

        return await self._generate(
            prompt, types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024)
        )


    async def converse(
        self, *, system: str, tools: list[dict[str, Any]], message: str | None = None,
        results: list[ToolResult] | None = None, previous: str | None = None,
    ) -> AgentTurn:
        """One Interactions API turn. The conversation is stored server side and chained
        with previous_interaction_id, so thought signatures never have to round-trip here.
        Tools and the system instruction are per interaction and are sent every turn."""
        body: dict[str, Any] = {
            "model": self._model,
            "system_instruction": system,
            "tools": tools,
            "input": [
                {"type": "function_result", "call_id": r.call_id, "name": r.name,
                 "result": r.result, **({"is_error": True} if r.is_error else {})}
                for r in results
            ] if results else message,
        }
        if previous:
            body["previous_interaction_id"] = previous
        interaction = await self._paced(lambda: self._client.aio.interactions.create(**body))
        if interaction.status == "failed":
            raise LLMUnavailableError(f"Gemini interaction failed: {interaction.errors}")
        steps = interaction.steps or []
        calls = [
            ToolCall(id=s.id, name=s.name, arguments=dict(s.arguments or {}))
            for s in steps if getattr(s, "type", None) == "function_call"
        ]
        text = interaction.output_text or "".join(
            getattr(c, "text", None) or ""
            for s in steps if getattr(s, "type", None) == "model_output"
            for c in (s.content or [])
        )
        return AgentTurn(calls=calls, text=text.strip(), handle=interaction.id)


class UnconfiguredClient:
    """Used when GEMINI_API_KEY is unset: every call fails with a clear message."""

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")

    async def generate_text(self, prompt: str) -> str:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")

    async def converse(self, **_: Any) -> AgentTurn:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")


def default_llm() -> LLMClient:
    settings = get_settings()
    if not settings.gemini_api_key:
        return UnconfiguredClient()
    return GeminiClient(settings.gemini_api_key, settings.gemini_model,
                        max_attempts=settings.gemini_max_attempts,
                        requests_per_minute=settings.gemini_rpm)
