import json
import os
from collections.abc import Iterator

import httpx

from voice_sidecar import models
from voice_sidecar.adapters.external import http
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk

KEY_VARIABLE = "OPENAI_API_KEY"
SPEECH_URL = "https://api.openai.com/v1/audio/speech"


class OpenAiTts:
    """OpenAI `/audio/speech`, streaming raw 24 kHz mono int16 PCM as it arrives."""

    name = "openai"

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
        self.voice = voice
        self.model = model

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        if not text.strip():
            return
        body = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "pcm",
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        with (
            models.make_client(self._transport) as client,
            client.stream("POST", SPEECH_URL, headers=headers, json=body) as response,
        ):
            if not response.is_success:
                raise RuntimeError(
                    http.failure("openai", self._key, response, _pick_message)
                )
            yield from http.aligned(response.iter_bytes(), "openai")


def _pick_message(text: str) -> str:
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    error = parsed.get("error") if isinstance(parsed, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else text
