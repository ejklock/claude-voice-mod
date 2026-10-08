import importlib.util
import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from voice_sidecar.models import model_path
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.providers import TTS_PROVIDERS, create_tts

ADAPTER = "voice_sidecar.adapters.local.piper"
FETCH = "voice-sidecar models fetch piper"
VOICES = ("faber", "cadu", "jeff")

# The owner's real cache, located before the autouse guard repoints it.
_BASE = os.environ.get("XDG_CACHE_HOME")
REAL_HOME = Path(_BASE) if _BASE else Path.home() / ".cache"
REAL_CACHE = REAL_HOME / "claude-voice" / "models"


class FakeChunk:
    def __init__(
        self,
        pcm: Any = b"\x01\x00\x02\x00",
        sample_rate: Any = 22050,
        sample_width: Any = 2,
        sample_channels: Any = 1,
    ) -> None:
        self.audio_int16_bytes = pcm
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.sample_channels = sample_channels


class FakePiperVoice:
    """Stands in for piper.PiperVoice; records what the adapter asked of it."""

    loaded: ClassVar[list[tuple[str, str | None]]] = []
    calls: ClassVar[list[str]] = []
    chunks: ClassVar[list[Any]] = []

    @staticmethod
    def load(model_path: str, config_path: str | None = None) -> "FakePiperVoice":
        FakePiperVoice.loaded.append((model_path, config_path))
        return FakePiperVoice()

    def synthesize(self, text: str) -> Iterator[Any]:
        FakePiperVoice.calls.append(text)
        for chunk in FakePiperVoice.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


@pytest.fixture
def fake_piper(monkeypatch: pytest.MonkeyPatch) -> type[FakePiperVoice]:
    FakePiperVoice.loaded = []
    FakePiperVoice.calls = []
    FakePiperVoice.chunks = []
    module = types.ModuleType("piper")
    module.PiperVoice = FakePiperVoice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", module)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)
    return FakePiperVoice


def voice_files(voice: str) -> tuple[Path, Path]:
    onnx = model_path("piper", f"pt_BR-{voice}-medium.onnx")
    config = model_path("piper", f"pt_BR-{voice}-medium.onnx.json")
    private = Path(os.environ["XDG_CACHE_HOME"])
    assert onnx.is_relative_to(private), "the model cache escaped the private home"
    onnx.parent.mkdir(parents=True, exist_ok=True)
    onnx.write_bytes(b"onnx")
    config.write_bytes(b"{}")
    return onnx, config


def unavailable(voice: str) -> str:
    with pytest.raises(ProviderUnavailable) as error:
        create_tts("piper", {"voice": voice})
    return error.value.reason


@pytest.mark.parametrize(
    "voice", ["", "edresson", "Faber", "../faber", "faber/../../x"]
)
def test_an_unknown_voice_names_it_and_the_three_known_ones(
    monkeypatch: pytest.MonkeyPatch, voice: str
) -> None:
    monkeypatch.setitem(sys.modules, "piper", None)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)

    assert unavailable(voice) == (
        f"piper has no voice {voice!r}; known voices: faber, cadu, jeff"
    )


def test_without_the_extra_the_reason_names_the_sync_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice_files("faber")
    monkeypatch.setitem(sys.modules, "piper", None)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)

    assert unavailable("faber") == (
        "the piper package is not installed; run `uv sync --extra piper`"
    )


@pytest.mark.parametrize(
    "missing", ["pt_BR-cadu-medium.onnx", "pt_BR-cadu-medium.onnx.json"]
)
def test_a_missing_file_names_it_and_the_fetch_command(
    fake_piper: type[FakePiperVoice], missing: str
) -> None:
    voice_files("cadu")
    model_path("piper", missing).unlink()

    assert unavailable("cadu") == (
        f"the piper file {missing} is not in the cache; run `{FETCH}`"
    )
    assert fake_piper.loaded == []


def test_without_the_files_piper_is_never_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "piper", None)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)

    reason = unavailable("jeff")

    assert FETCH in reason
    assert "pt_BR-jeff-medium.onnx" in reason


@pytest.fixture
def tts(fake_piper: type[FakePiperVoice]) -> Any:
    voice_files("faber")
    return create_tts("piper", {"voice": "faber"})


def test_the_voice_is_loaded_once_from_the_cached_files(
    fake_piper: type[FakePiperVoice],
) -> None:
    onnx, config = voice_files("jeff")

    made: Any = create_tts("piper", {"voice": "jeff"})
    fake_piper.chunks = [FakeChunk()]
    list(made.synthesize("a"))
    list(made.synthesize("b"))

    assert fake_piper.loaded == [(str(onnx), str(config))]
    assert made.name == "piper"
    assert made.voice == "jeff"


def test_the_voice_defaults_to_faber(fake_piper: type[FakePiperVoice]) -> None:
    onnx, config = voice_files("faber")

    create_tts("piper", {})

    assert fake_piper.loaded == [(str(onnx), str(config))]


def test_one_chunk_per_piper_chunk_in_order(
    tts: Any, fake_piper: type[FakePiperVoice]
) -> None:
    fake_piper.chunks = [
        FakeChunk(pcm=b"\x01\x00", sample_rate=22050),
        FakeChunk(pcm=b"\x02\x00\x03\x00", sample_rate=16000),
    ]

    chunks = list(tts.synthesize("Oi. Tchau."))

    assert [(c.pcm, c.sample_rate) for c in chunks] == [
        (b"\x01\x00", 22050),
        (b"\x02\x00\x03\x00", 16000),
    ]
    assert fake_piper.calls == ["Oi. Tchau."]


def test_the_first_chunk_arrives_before_the_second_is_produced(
    tts: Any, fake_piper: type[FakePiperVoice]
) -> None:
    fake_piper.chunks = [FakeChunk(), RuntimeError("second sentence failed")]
    stream = tts.synthesize("Oi. Tchau.")

    assert next(stream).pcm == b"\x01\x00\x02\x00"
    with pytest.raises(RuntimeError, match="second sentence failed"):
        next(stream)


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_yields_nothing_and_never_calls_piper(
    tts: Any, fake_piper: type[FakePiperVoice], text: str
) -> None:
    assert list(tts.synthesize(text)) == []
    assert fake_piper.calls == []


def test_an_empty_chunk_is_skipped(tts: Any, fake_piper: type[FakePiperVoice]) -> None:
    fake_piper.chunks = [FakeChunk(pcm=b""), FakeChunk(pcm=b"\x01\x00")]

    assert [c.pcm for c in tts.synthesize("oi")] == [b"\x01\x00"]


def test_a_sample_rate_of_one_is_accepted(
    tts: Any, fake_piper: type[FakePiperVoice]
) -> None:
    fake_piper.chunks = [FakeChunk(sample_rate=1)]

    assert [c.sample_rate for c in tts.synthesize("oi")] == [1]


def test_an_error_from_piper_propagates(
    tts: Any, fake_piper: type[FakePiperVoice]
) -> None:
    fake_piper.chunks = [RuntimeError("onnx exploded")]

    with pytest.raises(RuntimeError, match="onnx exploded"):
        list(tts.synthesize("oi"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_rate", True),
        ("sample_rate", 0),
        ("sample_rate", -1),
        ("sample_rate", 22050.0),
        ("sample_rate", "22050"),
        ("sample_width", 1),
        ("sample_width", 4),
        ("sample_width", True),
        ("sample_channels", 2),
        ("sample_channels", 0),
        ("sample_channels", True),
        ("pcm", b"\x01"),
        ("pcm", "text"),
        ("pcm", bytearray(b"\x01\x00")),
        ("pcm", None),
    ],
)
def test_a_chunk_field_that_breaks_the_contract_is_an_error(
    tts: Any, fake_piper: type[FakePiperVoice], field: str, value: Any
) -> None:
    fake_piper.chunks = [FakeChunk(**{field: value})]

    with pytest.raises(RuntimeError) as error:
        list(tts.synthesize("oi"))

    problems = {
        "sample_rate": "is not a positive int",
        "sample_width": "is not 2",
        "sample_channels": "is not 1",
        "pcm": "is not bytes of even length",
    }
    name = "audio_int16_bytes" if field == "pcm" else field
    assert str(error.value) == f"piper returned a chunk whose {name} {problems[field]}"


def test_the_registry_lists_piper_with_its_three_voices() -> None:
    assert TTS_PROVIDERS["piper"].default_voices == VOICES


def test_the_adapter_is_not_imported_until_a_piper_voice_is_created(
    fake_piper: type[FakePiperVoice],
) -> None:
    voice_files("faber")
    assert ADAPTER not in sys.modules

    create_tts("piper", {"voice": "faber"})

    assert ADAPTER in sys.modules


def _real_skip_reason() -> str | None:
    if os.environ.get("MUTANT_UNDER_TEST"):
        return "mutmut forks must not load onnxruntime"
    if importlib.util.find_spec("piper") is None:
        return "the piper extra is not installed; run `uv sync --extra piper`"
    for name in ("pt_BR-faber-medium.onnx", "pt_BR-faber-medium.onnx.json"):
        if not (REAL_CACHE / "piper" / name).is_file():
            return f"{name} is not cached; run `{FETCH}`"
    return None


@pytest.mark.skipif(_real_skip_reason() is not None, reason=_real_skip_reason() or "")
def test_the_real_model_speaks_pt_br(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(REAL_HOME))

    chunks = list(create_tts("piper", {"voice": "faber"}).synthesize("Olá, mundo."))

    pcm = b"".join(chunk.pcm for chunk in chunks)
    assert {chunk.sample_rate for chunk in chunks} == {22050}
    assert len(pcm) % 2 == 0
    assert len(pcm) >= 22050 * 2 * 3 // 10
