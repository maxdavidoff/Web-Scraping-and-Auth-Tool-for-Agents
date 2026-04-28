from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_MISTRAL_MODEL = "mistral-small-latest"


class LLMClientError(RuntimeError):
    """Raised when the provider-neutral LLM client cannot complete a request."""


@dataclass(frozen=True)
class MistralChatClient:
    api_key: str
    model: str = DEFAULT_MISTRAL_MODEL
    base_url: str = MISTRAL_BASE_URL
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> "MistralChatClient":
        api_key = os.getenv("MISTRAL_API_KEY", "").strip()
        if not api_key:
            raise LLMClientError("Set MISTRAL_API_KEY before calling the live Mistral intent extractor.")

        return cls(
            api_key=api_key,
            model=model or os.getenv("MISTRAL_MODEL", DEFAULT_MISTRAL_MODEL),
            base_url=base_url or os.getenv("MISTRAL_BASE_URL", MISTRAL_BASE_URL),
            timeout_seconds=timeout_seconds,
        )

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        request = urllib.request.Request(
            _join_url(self.base_url, MISTRAL_CHAT_COMPLETIONS_PATH),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMClientError(f"Mistral API returned HTTP {exc.code}: {_compact_error_body(body)}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"Mistral API request failed: {exc.reason}") from exc

        try:
            data = json.loads(body)
            return _extract_message_content(data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMClientError("Mistral API response did not contain a usable assistant JSON message.") from exc


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _extract_message_content(data: Mapping[str, Any]) -> str:
    choices = data["choices"]
    if not choices:
        raise ValueError("No choices in response.")

    content = choices[0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for chunk in content:
            if isinstance(chunk, Mapping) and chunk.get("type") == "text":
                text_parts.append(str(chunk.get("text", "")))
        text = "".join(text_parts).strip()
        if text:
            return text
    raise ValueError("Unsupported Mistral message content shape.")


def _compact_error_body(body: str) -> str:
    text = " ".join(body.split())
    return text[:500]
