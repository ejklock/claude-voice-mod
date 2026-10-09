import json
import os
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import httpx

from voice_sidecar import models
from voice_sidecar.adapters.external import http
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk

KEY_VARIABLE = "ELEVENLABS_API_KEY"
BASE_URL = "https://api.elevenlabs.io"
AUTO_VOICE = "auto"
ACCOUNT_PAGE_SIZE = 100
ACCOUNT_MAX_PAGES = 10
LIBRARY_HINT_VOICES = 3
NO_VOICE = "no pt-BR voice in the ElevenLabs account"


class ElevenLabsTts:
    """ElevenLabs text-to-speech, streaming raw 24 kHz mono int16 PCM as it arrives."""

    name = "elevenlabs"

    def __init__(
        self,
        voice: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = os.environ.get(KEY_VARIABLE, "").strip()
        if not key:
            raise ProviderUnavailable(f"{KEY_VARIABLE} is not set")
        self._key = key
        self._transport = transport
        self.model = model
        self.voice = voice if voice != AUTO_VOICE else self._first_pt_br_voice()

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        if not text.strip():
            return
        url = f"{BASE_URL}/v1/text-to-speech/{quote(self.voice, safe='')}/stream"
        body = {"text": text, "model_id": self.model}
        with (
            models.make_client(self._transport) as client,
            client.stream(
                "POST",
                url,
                params={"output_format": "pcm_24000"},
                headers=self._headers(),
                json=body,
            ) as response,
        ):
            if not response.is_success:
                raise RuntimeError(self._failure(response))
            yield from http.aligned(response.iter_bytes(), self.name)

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self._key}

    def _failure(self, response: httpx.Response) -> str:
        return http.failure(self.name, self._key, response, _pick_message)

    def _first_pt_br_voice(self) -> str:
        with models.make_client(self._transport) as client:
            try:
                found = self._scan_account(client)
            except httpx.HTTPError as error:
                raise ProviderUnavailable(
                    f"elevenlabs request failed: {type(error).__name__}"
                ) from None
            if found is not None:
                return found
            raise ProviderUnavailable(f"{NO_VOICE}{self._library_hint(client)}")

    def _scan_account(self, client: httpx.Client) -> str | None:
        params: dict[str, str] = {"page_size": str(ACCOUNT_PAGE_SIZE)}
        for _ in range(ACCOUNT_MAX_PAGES):
            response = client.get(
                f"{BASE_URL}/v2/voices", params=params, headers=self._headers()
            )
            if not response.is_success:
                raise ProviderUnavailable(self._failure(response))
            page = _object(response)
            for entry in page["voices"]:
                if _is_pt_br(entry):
                    return str(entry["voice_id"])
            token = page.get("next_page_token")
            if page.get("has_more") is not True or not isinstance(token, str):
                return None
            if not token:
                return None
            params = {**params, "next_page_token": token}
        return None

    def _library_hint(self, client: httpx.Client) -> str:
        """Shared pt-BR voices to add, or nothing when the library is unreadable."""
        try:
            response = client.get(
                f"{BASE_URL}/v1/shared-voices",
                params={
                    "language": "pt",
                    "locale": "pt-BR",
                    "page_size": str(LIBRARY_HINT_VOICES),
                },
                headers=self._headers(),
            )
            voices = response.json()["voices"] if response.is_success else []
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return "; add one from the voice library"
        named = [
            f"{v['name']} ({v['voice_id']})"
            for v in voices
            if isinstance(v, dict)
            and isinstance(v.get("name"), str)
            and isinstance(v.get("voice_id"), str)
        ][:LIBRARY_HINT_VOICES]
        suffix = f": {', '.join(named)}" if named else ""
        return f"; add one from the voice library{suffix}"


def _object(response: httpx.Response) -> dict[str, Any]:
    """The account page, parsed; malformed shapes are unavailable, never a crash."""
    try:
        page = response.json()
    except ValueError:
        page = None
    voices = page.get("voices") if isinstance(page, dict) else None
    if not isinstance(voices, list) or not all(_has_id(v) for v in voices):
        raise ProviderUnavailable("elevenlabs returned an unreadable voice list")
    return cast(dict[str, Any], page)


def _has_id(entry: Any) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("voice_id"), str)


def _is_pt_br(entry: dict[str, Any]) -> bool:
    languages = entry.get("verified_languages")
    if not isinstance(languages, list):
        return False
    return any(_language_is_pt_br(item) for item in languages if isinstance(item, dict))


def _language_is_pt_br(item: dict[str, Any]) -> bool:
    locale = item.get("locale")
    language = item.get("language")
    accent = item.get("accent")
    if isinstance(locale, str) and locale.lower() == "pt-br":
        return True
    return (
        isinstance(language, str)
        and language.lower() == "pt"
        and isinstance(accent, str)
        and "brazil" in accent.lower()
    )


def _pick_message(text: str) -> str:
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    if isinstance(detail, dict):
        message = detail.get("message")
    elif isinstance(detail, list) and detail and isinstance(detail[0], dict):
        message = detail[0].get("msg")
    else:
        message = None
    return message if isinstance(message, str) else text
