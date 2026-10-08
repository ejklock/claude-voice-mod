import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest

from voice_sidecar.models import model_path
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.providers import TTS_PROVIDERS, create_tts

ADAPTER = "voice_sidecar.adapters.local.kokoro"
BAD_SAMPLES = "kokoro returned samples that are not a 1-D float32 array"
BAD_RATE = "kokoro returned a sample rate that is not a positive int"
VOICES = ["pf_dora", "pm_alex", "af_heart"]

# The owner's real cache, located before the autouse guard repoints it.
_BASE = os.environ.get("XDG_CACHE_HOME")
REAL_HOME = Path(_BASE) if _BASE else Path.home() / ".cache"
REAL_CACHE = REAL_HOME / "claude-voice" / "models"


class FakeKokoro:
    """Stands in for kokoro_onnx.Kokoro; records what the adapter asked of it."""

    constructed: ClassVar[list[tuple[str, str]]] = []
    calls: ClassVar[list[tuple[str, str, str]]] = []
    result: ClassVar[Any] = None

    def __init__(self, model_path: str, voices_path: str) -> None:
        FakeKokoro.constructed.append((model_path, voices_path))

    def get_voices(self) -> list[str]:
        return VOICES

    def create(self, text: str, voice: str, lang: str = "en-us") -> Any:
        FakeKokoro.calls.append((text, voice, lang))
        if isinstance(FakeKokoro.result, Exception):
            raise FakeKokoro.result
        return FakeKokoro.result


@pytest.fixture
def fake_kokoro(monkeypatch: pytest.MonkeyPatch) -> type[FakeKokoro]:
    FakeKokoro.constructed = []
    FakeKokoro.calls = []
    FakeKokoro.result = None
    module = types.ModuleType("kokoro_onnx")
    module.Kokoro = FakeKokoro  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kokoro_onnx", module)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)
    return FakeKokoro


@pytest.fixture
def model_files() -> tuple[Path, Path]:
    onnx = model_path("kokoro", "kokoro-v1.0.onnx")
    voices = model_path("kokoro", "voices-v1.0.bin")
    private = Path(os.environ["XDG_CACHE_HOME"])
    assert onnx.is_relative_to(private), "the model cache escaped the private home"
    onnx.parent.mkdir(parents=True)
    onnx.write_bytes(b"onnx")
    voices.write_bytes(b"voices")
    return onnx, voices


def unavailable(voice: str) -> str:
    with pytest.raises(ProviderUnavailable) as error:
        create_tts("kokoro", {"voice": voice})
    return error.value.reason


def test_without_the_extra_the_reason_names_the_sync_command(
    monkeypatch: pytest.MonkeyPatch, model_files: tuple[Path, Path]
) -> None:
    monkeypatch.setitem(sys.modules, "kokoro_onnx", None)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)

    assert unavailable("pf_dora") == (
        "the kokoro_onnx package is not installed; run `uv sync --extra kokoro`"
    )


def test_without_the_files_kokoro_onnx_is_never_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "kokoro_onnx", None)
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)

    assert "voice-sidecar models fetch kokoro" in unavailable("pf_dora")


@pytest.mark.parametrize(
    "missing", ["kokoro-v1.0.onnx", "voices-v1.0.bin"], ids=["model", "voices"]
)
def test_a_missing_model_file_names_it_and_the_fetch_command(
    fake_kokoro: type[FakeKokoro], model_files: tuple[Path, Path], missing: str
) -> None:
    model_path("kokoro", missing).unlink()

    assert unavailable("pf_dora") == (
        f"the kokoro file {missing} is not in the cache; "
        "run `voice-sidecar models fetch kokoro`"
    )
    assert fake_kokoro.constructed == []


def test_both_files_missing_names_the_model_first(
    fake_kokoro: type[FakeKokoro],
) -> None:
    assert "kokoro-v1.0.onnx" in unavailable("pf_dora")
    assert fake_kokoro.constructed == []


@pytest.mark.parametrize("voice", ["pt_nobody", "pf_dor", ""])
def test_a_voice_not_in_the_model_is_unavailable(
    fake_kokoro: type[FakeKokoro], model_files: tuple[Path, Path], voice: str
) -> None:
    assert unavailable(voice) == f"kokoro has no voice {voice!r}"


def test_the_model_is_built_from_the_cached_files(
    fake_kokoro: type[FakeKokoro], model_files: tuple[Path, Path]
) -> None:
    tts = create_tts("kokoro", {"voice": "pm_alex"})

    onnx, voices = model_files
    assert fake_kokoro.constructed == [(str(onnx), str(voices))]
    assert tts.name == "kokoro"


def test_the_voice_defaults_to_pf_dora(
    fake_kokoro: type[FakeKokoro], model_files: tuple[Path, Path]
) -> None:
    pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    fake_kokoro.result = ([], 24000)

    with pytest.raises(RuntimeError):
        list(create_tts("kokoro", {}).synthesize("oi"))

    assert fake_kokoro.calls == [("oi", "pf_dora", "pt-br")]


def test_the_registry_lists_kokoro_with_its_two_voices() -> None:
    assert TTS_PROVIDERS["kokoro"].default_voices == ("pf_dora", "pm_alex")


def test_the_adapter_is_not_imported_until_a_kokoro_voice_is_created(
    fake_kokoro: type[FakeKokoro], model_files: tuple[Path, Path]
) -> None:
    assert ADAPTER not in sys.modules

    create_tts("kokoro", {"voice": "pf_dora"})

    assert ADAPTER in sys.modules


@pytest.fixture
def tts(fake_kokoro: type[FakeKokoro], model_files: tuple[Path, Path]) -> Any:
    return create_tts("kokoro", {"voice": "pf_dora"})


def synthesize(tts: Any, samples: list[float], rate: int = 24000) -> bytes:
    np = pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    FakeKokoro.result = (np.array(samples, dtype=np.float32), rate)
    return b"".join(chunk.pcm for chunk in tts.synthesize("Olá."))


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (1.0, 32767),
        (-1.0, -32767),
        (1.5, 32767),
        (-1.5, -32767),
        (0.25, 8192),
        (0.0, 0),
        (float("nan"), 0),
        (float("inf"), 32767),
        (float("-inf"), -32767),
    ],
)
def test_a_float_sample_becomes_a_clipped_rounded_s16_value(
    tts: Any, sample: float, expected: int
) -> None:
    pcm = synthesize(tts, [sample])

    assert int.from_bytes(pcm, "little", signed=True) == expected
    assert len(pcm) == 2


def test_the_samples_are_little_endian_mono_in_order(tts: Any) -> None:
    assert synthesize(tts, [1.0, -1.0, 0.0]) == bytes([0xFF, 0x7F, 0x01, 0x80, 0, 0])


def test_create_gets_the_text_the_voice_and_pt_br(tts: Any) -> None:
    synthesize(tts, [0.5])

    assert FakeKokoro.calls == [("Olá.", "pf_dora", "pt-br")]


def test_one_chunk_at_the_rate_create_returned(tts: Any) -> None:
    np = pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    FakeKokoro.result = (np.zeros(5000, dtype=np.float32), 22050)

    chunks = list(tts.synthesize("oi"))

    assert [(len(c.pcm), c.sample_rate) for c in chunks] == [(10000, 22050)]


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_yields_nothing_and_never_calls_create(tts: Any, text: str) -> None:
    FakeKokoro.result = RuntimeError("must not be called")

    assert list(tts.synthesize(text)) == []
    assert FakeKokoro.calls == []


def test_a_sample_rate_of_one_is_a_positive_int(tts: Any) -> None:
    np = pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    FakeKokoro.result = (np.zeros(3, dtype=np.float32), 1)

    assert [c.sample_rate for c in tts.synthesize("oi")] == [1]


def test_no_samples_yield_no_chunk(tts: Any) -> None:
    np = pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    FakeKokoro.result = (np.zeros(0, dtype=np.float32), 24000)

    assert list(tts.synthesize("oi")) == []


def test_an_error_from_create_propagates(tts: Any) -> None:
    FakeKokoro.result = RuntimeError("onnx exploded")

    with pytest.raises(RuntimeError, match="onnx exploded"):
        list(tts.synthesize("oi"))


@pytest.mark.parametrize("kind", ["two_d", "float64", "int16"])
def test_samples_that_are_not_1d_float32_are_an_error(tts: Any, kind: str) -> None:
    np = pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    shapes = {
        "two_d": np.zeros((2, 3), dtype=np.float32),
        "float64": np.zeros(3, dtype=np.float64),
        "int16": np.zeros(3, dtype=np.int16),
    }
    FakeKokoro.result = (shapes[kind], 24000)

    with pytest.raises(RuntimeError) as error:
        list(tts.synthesize("oi"))

    assert str(error.value) == BAD_SAMPLES


def test_a_result_that_is_not_samples_and_a_rate_is_an_error(tts: Any) -> None:
    pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    FakeKokoro.result = ([0.0], 24000)

    with pytest.raises(RuntimeError) as error:
        list(tts.synthesize("oi"))

    assert str(error.value) == BAD_SAMPLES


@pytest.mark.parametrize("rate", [0, -1, 24000.0, "24000", True])
def test_a_sample_rate_that_is_not_a_positive_int_is_an_error(
    tts: Any, rate: Any
) -> None:
    np = pytest.importorskip("numpy", reason="numpy comes with the kokoro extra")
    FakeKokoro.result = (np.zeros(3, dtype=np.float32), rate)

    with pytest.raises(RuntimeError) as error:
        list(tts.synthesize("oi"))

    assert str(error.value) == BAD_RATE


def _real_skip_reason() -> str | None:
    if os.environ.get("MUTANT_UNDER_TEST"):
        return "mutmut forks must not load onnxruntime"
    if importlib.util.find_spec("kokoro_onnx") is None:
        return "the kokoro extra is not installed; run `uv sync --extra kokoro`"
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if not (REAL_CACHE / "kokoro" / name).is_file():
            return f"{name} is not cached; run `voice-sidecar models fetch kokoro`"
    return None


@pytest.mark.skipif(_real_skip_reason() is not None, reason=_real_skip_reason() or "")
def test_the_real_model_speaks_pt_br(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(REAL_HOME))

    chunks = list(create_tts("kokoro", {"voice": "pf_dora"}).synthesize("Olá, mundo."))

    pcm = b"".join(chunk.pcm for chunk in chunks)
    assert {chunk.sample_rate for chunk in chunks} == {24000}
    assert len(pcm) % 2 == 0
    assert len(pcm) >= 24000 * 2 * 3 // 10
