from collections.abc import Iterator
from typing import Any

from voice_sidecar.models import model_path
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk

VOICES = ("faber", "cadu", "jeff")
SAMPLE_WIDTH = 2
SAMPLE_CHANNELS = 1


class PiperTts:
    """Piper on onnxruntime; one chunk per sentence, yielded as it is synthesized."""

    name = "piper"

    def __init__(self, voice: str) -> None:
        if voice not in VOICES:
            raise ProviderUnavailable(
                f"piper has no voice {voice!r}; known voices: {', '.join(VOICES)}"
            )
        files = []
        for filename in (
            f"pt_BR-{voice}-medium.onnx",
            f"pt_BR-{voice}-medium.onnx.json",
        ):
            path = model_path("piper", filename)
            if not path.is_file():
                raise ProviderUnavailable(
                    f"the piper file {filename} is not in the cache; "
                    "run `voice-sidecar models fetch piper`"
                )
            files.append(str(path))
        # Last, so a run without the model files never loads onnxruntime, which
        # aborts a forked child when it exits.
        try:
            from piper import PiperVoice
        except ImportError as error:
            raise ProviderUnavailable(
                "the piper package is not installed; run `uv sync --extra piper`"
            ) from error
        self._voice = PiperVoice.load(files[0], config_path=files[1])
        self.voice = voice

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        if not text.strip():
            return
        for chunk in self._voice.synthesize(text):
            pcm, rate = _parse(chunk)
            if pcm:
                yield AudioChunk(pcm=pcm, sample_rate=rate)


def _parse(chunk: Any) -> tuple[bytes, int]:
    rate = chunk.sample_rate
    if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
        raise _bad("sample_rate", "is not a positive int")
    for field, expected in (
        ("sample_width", SAMPLE_WIDTH),
        ("sample_channels", SAMPLE_CHANNELS),
    ):
        value = getattr(chunk, field)
        if not isinstance(value, int) or isinstance(value, bool) or value != expected:
            raise _bad(field, f"is not {expected}")
    pcm = chunk.audio_int16_bytes
    if not isinstance(pcm, bytes) or len(pcm) % SAMPLE_WIDTH:
        raise _bad("audio_int16_bytes", "is not bytes of even length")
    return pcm, rate


def _bad(field: str, problem: str) -> RuntimeError:
    return RuntimeError(f"piper returned a chunk whose {field} {problem}")
