from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioChunk:
    """Mono signed 16-bit little-endian PCM."""

    pcm: bytes
    sample_rate: int


class TextToSpeech(Protocol):
    name: str

    def synthesize(self, text: str) -> Iterator[AudioChunk]: ...
