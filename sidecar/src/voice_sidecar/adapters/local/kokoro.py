from collections.abc import Iterator
from typing import Any

from voice_sidecar.models import model_path
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk

MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"
LANGUAGE = "pt-br"
PCM_PEAK = 32767


class KokoroTts:
    """Kokoro on onnxruntime; `create` returns the whole utterance, so one chunk."""

    name = "kokoro"

    def __init__(self, voice: str) -> None:
        files = []
        for filename in (MODEL_FILE, VOICES_FILE):
            path = model_path("kokoro", filename)
            if not path.is_file():
                raise ProviderUnavailable(
                    f"the kokoro file {filename} is not in the cache; "
                    "run `voice-sidecar models fetch kokoro`"
                )
            files.append(str(path))
        # Last, so a run without the model files never loads onnxruntime, which
        # aborts a forked child when it exits.
        try:
            from kokoro_onnx import Kokoro
        except ImportError as error:
            raise ProviderUnavailable(
                "the kokoro_onnx package is not installed; run `uv sync --extra kokoro`"
            ) from error
        self._model = Kokoro(files[0], files[1])
        if voice not in self._model.get_voices():
            raise ProviderUnavailable(f"kokoro has no voice {voice!r}")
        self.voice = voice

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        if not text.strip():
            return
        samples, rate = self._model.create(text, self.voice, lang=LANGUAGE)
        pcm = _to_pcm(samples)
        if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
            raise RuntimeError(
                "kokoro returned a sample rate that is not a positive int"
            )
        if pcm:
            yield AudioChunk(pcm=pcm, sample_rate=rate)


def _to_pcm(samples: Any) -> bytes:
    """Float samples in [-1, 1] as mono s16le; NaN is silence, overshoot is clipped."""
    import numpy as np

    if (
        not isinstance(samples, np.ndarray)
        or samples.ndim != 1
        or samples.dtype != np.float32
    ):
        raise RuntimeError("kokoro returned samples that are not a 1-D float32 array")
    clean = np.nan_to_num(samples.astype(np.float64), nan=0.0)
    scaled = np.rint(np.clip(clean, -1.0, 1.0) * PCM_PEAK)
    return bytes(scaled.astype("<i2").tobytes())
