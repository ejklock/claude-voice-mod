from collections.abc import Callable, Iterator

import pytest

from voice_sidecar.audio.speaker import SoundDeviceSpeaker
from voice_sidecar.bench.tts import BenchRow, BenchVoice, render_table, run_tts_bench
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk, TextToSpeech

RATE = 24000


def chunk(samples: int, rate: int = RATE, fill: int = 1) -> AudioChunk:
    return AudioChunk(pcm=bytes([fill, 0]) * samples, sample_rate=rate)


class FakeTts:
    name = "fake"

    def __init__(self, chunks: list[AudioChunk], error: Exception | None = None):
        self.chunks = chunks
        self.error = error
        self.texts: list[str] = []

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        self.texts.append(text)
        yield from self.chunks
        if self.error is not None:
            raise self.error


class Clock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class RecordingSpeaker:
    def __init__(self) -> None:
        self.played: list[AudioChunk] = []

    def play(self, chunk: AudioChunk) -> None:
        self.played.append(chunk)

    def close(self) -> None:
        pass


def voice(label: str, tts: TextToSpeech) -> BenchVoice:
    return BenchVoice(label=label, create=lambda: tts)


def unavailable(reason: str) -> Callable[[], TextToSpeech]:
    def create() -> TextToSpeech:
        raise ProviderUnavailable(reason)

    return create


def test_an_ok_row_carries_the_four_timings() -> None:
    tts = FakeTts([chunk(6000), chunk(6000)])

    [row] = run_tts_bench(
        [voice("fake:a", tts)], "olá", None, Clock(10.0, 10.1204, 10.35)
    )

    assert row.voice == "fake:a"
    assert row.status == "ok"
    assert row.reason is None
    assert row.first_audio_s == pytest.approx(0.1204)
    assert row.synthesis_s == pytest.approx(0.35)
    assert row.audio_s == pytest.approx(0.5)
    assert row.real_time_factor == pytest.approx(0.7)
    assert tts.texts == ["olá"]


def test_audio_seconds_follow_each_chunk_sample_rate() -> None:
    tts = FakeTts([chunk(24000, 24000), chunk(11025, 22050)])

    [row] = run_tts_bench([voice("v", tts)], "x", None, Clock(0.0, 0.1, 0.2))

    assert row.audio_s == pytest.approx(1.5)


def test_an_unavailable_voice_is_skipped_and_the_next_still_runs() -> None:
    voices = [
        BenchVoice("fake:gone", unavailable("OPENAI_API_KEY is not set")),
        voice("fake:b", FakeTts([chunk(2400)])),
    ]

    skipped, ok = run_tts_bench(voices, "x", None, Clock(0.0, 0.1, 0.2))

    assert skipped == BenchRow(
        voice="fake:gone",
        status="skipped",
        first_audio_s=None,
        synthesis_s=None,
        audio_s=None,
        real_time_factor=None,
        reason="OPENAI_API_KEY is not set",
    )
    assert ok.status == "ok"


def test_a_voice_failing_mid_stream_is_failed_with_the_first_error_line() -> None:
    voices = [
        voice("fake:a", FakeTts([chunk(2400)], RuntimeError("boom\nsecond line"))),
        voice("fake:b", FakeTts([chunk(2400)])),
    ]

    failed, ok = run_tts_bench(voices, "x", None, Clock(0.0, 0.1, 1.0, 1.1, 1.2))

    assert failed.voice == "fake:a"
    assert failed.status == "failed"
    assert failed.reason == "boom"
    assert failed.real_time_factor is None
    assert ok.status == "ok"


def test_an_error_without_a_message_is_reported_by_its_type() -> None:
    tts = FakeTts([], RuntimeError())

    [row] = run_tts_bench([voice("v", tts)], "x", None, Clock(0.0, 1.0))

    assert row.reason == "RuntimeError"


def test_a_voice_yielding_nothing_is_failed_with_no_audio() -> None:
    [row] = run_tts_bench([voice("v", FakeTts([]))], "x", None, Clock(0.0, 1.0))

    assert row.voice == "v"
    assert row.status == "failed"
    assert row.reason == "no audio"
    assert row.real_time_factor is None


def test_chunks_without_samples_are_failed_with_no_audio() -> None:
    [row] = run_tts_bench(
        [voice("v", FakeTts([chunk(0)]))], "x", None, Clock(0.0, 0.1, 0.2)
    )

    assert (row.status, row.reason) == ("failed", "no audio")


def test_the_speaker_receives_every_chunk_of_every_voice_in_order() -> None:
    first = [chunk(100, fill=1), chunk(100, fill=2)]
    second = [chunk(100, fill=3)]
    speaker = RecordingSpeaker()

    run_tts_bench(
        [voice("a", FakeTts(first)), voice("b", FakeTts(second))],
        "x",
        speaker,
        Clock(0.0, 0.1, 0.2, 1.0, 1.1, 1.2),
    )

    assert speaker.played == [*first, *second]


def test_playing_does_not_change_the_timings() -> None:
    chunks = [chunk(2400), chunk(2400)]

    [silent] = run_tts_bench(
        [voice("v", FakeTts(chunks))], "x", None, Clock(0.0, 0.1, 0.3)
    )
    [played] = run_tts_bench(
        [voice("v", FakeTts(chunks))], "x", RecordingSpeaker(), Clock(0.0, 0.1, 0.3)
    )

    assert played == silent


def test_a_speaker_failure_marks_the_row_failed() -> None:
    class BrokenSpeaker(RecordingSpeaker):
        def play(self, chunk: AudioChunk) -> None:
            raise OSError("no output device")

    [row] = run_tts_bench(
        [voice("v", FakeTts([chunk(2400)]))],
        "x",
        BrokenSpeaker(),
        Clock(0.0, 0.1, 0.2),
    )

    assert row.status == "failed"
    assert row.reason == "no output device"


def test_the_table_aligns_one_row_per_voice() -> None:
    rows = [
        BenchRow("say:Luciana", "ok", 0.1204, 0.35, 2.5, 0.14, None),
        BenchRow("x:y", "skipped", None, None, None, None, "no key"),
    ]

    assert render_table(rows).splitlines() == [
        "voice" + " " * 8 + "status" + " " * 3 + "first audio ms"
        "  synthesis ms  audio s  synth/audio  note",
        "say:Luciana  ok"
        + " " * 18
        + "120"
        + " " * 11
        + "350"
        + " " * 5
        + "2.50"
        + " " * 9
        + "0.14",
        "x:y"
        + " " * 10
        + "skipped"
        + " " * 15
        + "-"
        + " " * 13
        + "-"
        + " " * 8
        + "-"
        + " " * 12
        + "-  no key",
    ]


def test_the_ratio_column_is_headed_synth_audio_and_as_wide_as_its_header() -> None:
    [header, ok, skipped] = render_table(
        [
            BenchRow("v", "ok", 0.1, 0.2, 1.0, 0.14, None),
            BenchRow("w", "skipped", None, None, None, None, "no key"),
        ]
    ).splitlines()

    assert header.endswith("synth/audio  note")
    assert ok.endswith("0.14".rjust(11))
    assert skipped.endswith("-".rjust(11) + "  no key")


def test_the_table_rounds_times_to_milliseconds_and_seconds_to_two_decimals() -> None:
    [_, line] = render_table(
        [BenchRow("v", "ok", 0.0004, 1.2346, 3.14159, 0.3929, None)]
    ).splitlines()

    assert line.split() == ["v", "ok", "0", "1235", "3.14", "0.39"]


class FakeStream:
    def __init__(self, rate: int, log: list[str]) -> None:
        self.rate = rate
        self.log = log

    def write(self, data: bytes) -> None:
        self.log.append(f"write {self.rate} {len(data)}")

    def stop(self) -> None:
        self.log.append(f"stop {self.rate}")

    def close(self) -> None:
        self.log.append(f"close {self.rate}")


def test_the_device_speaker_reopens_its_stream_when_the_rate_changes() -> None:
    log: list[str] = []
    speaker = SoundDeviceSpeaker(open_stream=lambda rate: FakeStream(rate, log))

    speaker.play(chunk(10, 24000))
    speaker.play(chunk(10, 24000))
    speaker.play(chunk(10, 22050))
    speaker.close()
    speaker.close()

    assert log == [
        "write 24000 20",
        "write 24000 20",
        "stop 24000",
        "close 24000",
        "write 22050 20",
        "stop 22050",
        "close 22050",
    ]
