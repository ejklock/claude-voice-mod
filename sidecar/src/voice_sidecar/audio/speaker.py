from collections.abc import Callable
from typing import Protocol

from voice_sidecar.ports.tts import AudioChunk


class Speaker(Protocol):
    def play(self, chunk: AudioChunk) -> None: ...

    def close(self) -> None: ...


class OutputStream(Protocol):
    def write(self, data: bytes) -> object: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


def _open_sounddevice_stream(sample_rate: int) -> OutputStream:
    import sounddevice

    stream = sounddevice.RawOutputStream(
        samplerate=sample_rate, channels=1, dtype="int16"
    )
    stream.start()
    return stream  # type: ignore[no-any-return]


class SoundDeviceSpeaker:
    """Plays through the default output device; `write` blocks until consumed."""

    def __init__(
        self, open_stream: Callable[[int], OutputStream] = _open_sounddevice_stream
    ) -> None:
        self._open_stream = open_stream
        self._stream: OutputStream | None = None
        self._rate: int | None = None

    def play(self, chunk: AudioChunk) -> None:
        if self._stream is None or self._rate != chunk.sample_rate:
            self.close()
            self._stream = self._open_stream(chunk.sample_rate)
            self._rate = chunk.sample_rate
        self._stream.write(chunk.pcm)

    def close(self) -> None:
        stream, self._stream, self._rate = self._stream, None, None
        if stream is not None:
            stream.stop()
            stream.close()
