"""Thin Gemini wrapper behind a protocol so services can be tested without the API."""

from __future__ import annotations

from typing import Any, Protocol

from app.core.config import get_settings


class LLMUnavailableError(RuntimeError):
    pass


class LLMClient(Protocol):
    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str: ...

    async def generate_text(self, prompt: str) -> str: ...


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=0.0,
            ),
        )
        if not response.text:
            raise LLMUnavailableError("Gemini returned an empty response")
        return response.text

    async def generate_text(self, prompt: str) -> str:
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024),
        )
        if not response.text:
            raise LLMUnavailableError("Gemini returned an empty response")
        return response.text


class UnconfiguredClient:
    """Used when GEMINI_API_KEY is unset: every call fails with a clear message."""

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")

    async def generate_text(self, prompt: str) -> str:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")


def default_llm() -> LLMClient:
    settings = get_settings()
    if not settings.gemini_api_key:
        return UnconfiguredClient()
    return GeminiClient(settings.gemini_api_key, settings.gemini_model)
