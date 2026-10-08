from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from voice_sidecar.audio.speaker import Speaker
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk, TextToSpeech

BYTES_PER_SAMPLE = 2
HEADER = (
    "voice",
    "status",
    "first audio ms",
    "synthesis ms",
    "audio s",
    "synth/audio",
    "note",
)
NUMERIC_COLUMNS = frozenset({2, 3, 4, 5})


@dataclass(frozen=True)
class BenchVoice:
    label: str
    create: Callable[[], TextToSpeech]


@dataclass(frozen=True)
class BenchRow:
    voice: str
    status: Literal["ok", "skipped", "failed"]
    first_audio_s: float | None
    synthesis_s: float | None
    audio_s: float | None
    real_time_factor: float | None
    reason: str | None


def run_tts_bench(
    voices: Sequence[BenchVoice],
    text: str,
    speaker: Speaker | None,
    clock: Callable[[], float],
) -> list[BenchRow]:
    """Time each voice, then play what it produced so playback never skews the times."""
    return [_bench_one(voice, text, speaker, clock) for voice in voices]


def _bench_one(
    voice: BenchVoice, text: str, speaker: Speaker | None, clock: Callable[[], float]
) -> BenchRow:
    try:
        tts = voice.create()
    except ProviderUnavailable as unavailable:
        return _without_timings(voice.label, "skipped", unavailable.reason)
    try:
        chunks: list[AudioChunk] = []
        first_audio_s: float | None = None
        start = clock()
        for audio in tts.synthesize(text):
            if first_audio_s is None:
                first_audio_s = clock() - start
            chunks.append(audio)
        synthesis_s = clock() - start
        audio_s = sum(len(c.pcm) / BYTES_PER_SAMPLE / c.sample_rate for c in chunks)
        if first_audio_s is None or audio_s == 0:
            return _without_timings(voice.label, "failed", "no audio")
        if speaker is not None:
            for audio in chunks:
                speaker.play(audio)
    except Exception as error:
        return _without_timings(voice.label, "failed", _one_line(error))
    return BenchRow(
        voice=voice.label,
        status="ok",
        first_audio_s=first_audio_s,
        synthesis_s=synthesis_s,
        audio_s=audio_s,
        real_time_factor=synthesis_s / audio_s,
        reason=None,
    )


def _without_timings(
    label: str, status: Literal["skipped", "failed"], reason: str
) -> BenchRow:
    return BenchRow(label, status, None, None, None, None, reason)


def _one_line(error: Exception) -> str:
    lines = str(error).splitlines()
    return lines[0] if lines else type(error).__name__


def render_table(rows: Sequence[BenchRow]) -> str:
    cells = [HEADER, *(_cells(row) for row in rows)]
    widths = [max(len(line[i]) for line in cells) for i in range(len(HEADER))]
    return "\n".join(
        "  ".join(
            cell.rjust(width) if i in NUMERIC_COLUMNS else cell.ljust(width)
            for i, (cell, width) in enumerate(zip(line, widths, strict=True))
        ).rstrip()
        for line in cells
    )


def _cells(row: BenchRow) -> tuple[str, ...]:
    return (
        row.voice,
        row.status,
        _number(row.first_audio_s, 1000, 0),
        _number(row.synthesis_s, 1000, 0),
        _number(row.audio_s, 1, 2),
        _number(row.real_time_factor, 1, 2),
        row.reason or "",
    )


def _number(value: float | None, scale: int, decimals: int) -> str:
    return "-" if value is None else f"{value * scale:.{decimals}f}"
