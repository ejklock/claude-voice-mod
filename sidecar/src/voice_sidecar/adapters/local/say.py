import subprocess
import tempfile
import wave
from collections.abc import Iterator
from pathlib import Path

from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk

SAMPLE_RATE = 24000
FRAMES_PER_CHUNK = SAMPLE_RATE // 5


class SayTts:
    """The macOS `say` command; it can only write a file, so audio arrives whole."""

    name = "say"

    def __init__(self, voice: str) -> None:
        if voice not in _installed_voices():
            raise ProviderUnavailable(f"say has no voice {voice!r} installed")
        self.voice = voice

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        if not text.strip():
            return
        with tempfile.TemporaryDirectory(prefix="voice-say-") as directory:
            target = Path(directory) / "speech.wav"
            self._render(text, target)
            yield from _read_chunks(target)

    def _render(self, text: str, target: Path) -> None:
        # `--` keeps text that starts with a dash from being read as an option.
        result = subprocess.run(
            [
                "say",
                "-v",
                self.voice,
                "-o",
                str(target),
                f"--data-format=LEI16@{SAMPLE_RATE}",
                "--",
                text,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"say exited with code {result.returncode}: {result.stderr.strip()}"
            )


def _installed_voices() -> set[str]:
    """Every name `say` accepts: the listed name and the part before its qualifier."""
    try:
        listing = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as error:
        raise ProviderUnavailable("the say command is not installed") from error
    names: set[str] = set()
    for line in listing.stdout.splitlines():
        columns, _, _ = line.partition("#")
        parts = columns.rsplit(None, 1)
        if len(parts) == 2:
            names.add(parts[0])
            names.add(parts[0].partition(" (")[0])
    return names


def _read_chunks(source: Path) -> Iterator[AudioChunk]:
    with wave.open(str(source), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise RuntimeError("say wrote audio that is not mono 16-bit")
        while frames := reader.readframes(FRAMES_PER_CHUNK):
            yield AudioChunk(pcm=frames, sample_rate=reader.getframerate())
