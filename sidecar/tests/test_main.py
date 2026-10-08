import hashlib
import io
import re
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path

import httpx
import pytest

from voice_sidecar import models
from voice_sidecar.cli import main
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk, TextToSpeech
from voice_sidecar.providers import TTS_PROVIDERS, TtsProvider

DEFAULT_SENTENCE = (
    "Olá! Eu sou o Claude. Posso ler o seu código, rodar os testes e explicar "
    "o que encontrei."
)


class SpokenTts:
    name = "fake"

    def __init__(self, spoken: list[str]) -> None:
        self.spoken = spoken

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        self.spoken.append(text)
        yield AudioChunk(pcm=b"\x01\x00" * 24000, sample_rate=24000)


class SilentTts:
    name = "silent"

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        return iter(())


class InterruptedTts:
    name = "fake"

    def synthesize(self, text: str) -> Iterator[AudioChunk]:
        raise KeyboardInterrupt
        yield


@pytest.fixture
def spoken(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    texts: list[str] = []

    def factory(options: Mapping[str, str]) -> TextToSpeech:
        if options.get("voice") == "gone":
            raise ProviderUnavailable("FAKE_KEY is not set")
        if options.get("voice") == "interrupt":
            return InterruptedTts()
        return SpokenTts(texts)

    monkeypatch.delitem(TTS_PROVIDERS, "say")
    monkeypatch.delitem(TTS_PROVIDERS, "kokoro")
    monkeypatch.delitem(TTS_PROVIDERS, "piper")
    monkeypatch.setitem(TTS_PROVIDERS, "fake", TtsProvider(factory, ("a", "b")))
    return texts


def test_version_prints_the_plugin_version(
    capsys: pytest.CaptureFixture[str], plugin_version: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"{plugin_version}\n"


def test_help_names_the_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "--version" in capsys.readouterr().out


def test_unknown_flag_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--bogus"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage:")
    assert captured.out == ""


def test_no_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage: voice-sidecar ")
    assert captured.err.endswith("voice-sidecar: error: a flag is required\n")
    assert captured.out == ""


def test_a_bare_double_dash_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "required: command" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_omitted_argv_reads_the_process_arguments(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    plugin_version: str,
) -> None:
    monkeypatch.setattr("sys.argv", ["voice-sidecar", "--version"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"{plugin_version}\n"


def test_omitted_argv_without_arguments_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["voice-sidecar"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    assert "a flag is required" in capsys.readouterr().err


def test_bench_tts_runs_every_registry_voice_on_the_default_sentence(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play"])

    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines] == [
        ["voice", "status"],
        ["fake:a", "ok"],
        ["fake:b", "ok"],
    ]
    assert spoken == [DEFAULT_SENTENCE, DEFAULT_SENTENCE]


def test_bench_tts_runs_only_the_voices_and_text_it_is_given(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play", "--text", "oi", "--voice", "fake:b"])

    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:2] for line in lines[1:]] == [["fake:b", "ok"]]
    assert spoken == ["oi"]


def test_bench_tts_lists_an_unavailable_voice_as_skipped_with_its_reason(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play", "--voice", "fake:gone", "--voice", "fake:a"])

    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split(maxsplit=2)[:2] == ["fake:gone", "skipped"]
    assert lines[1].endswith("FAKE_KEY is not set")
    assert lines[2].split()[:2] == ["fake:a", "ok"]
    assert spoken == [DEFAULT_SENTENCE]


@pytest.mark.parametrize("spec", ["nope:x", "nocolon", "fake:", ":a"])
def test_bench_tts_with_a_bad_voice_spec_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], spoken: list[str], spec: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench", "tts", "--voice", spec])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage: voice-sidecar ")
    assert f"invalid voice {spec!r}" in captured.err
    assert captured.out == ""
    assert spoken == []


@pytest.mark.parametrize("text", ["", "  \n"])
def test_bench_tts_with_blank_text_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], spoken: list[str], text: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench", "tts", "--text", text])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.endswith(
        "voice-sidecar bench tts: error: the text must not be empty\n"
    )
    assert captured.out == ""


def test_bench_without_a_subcommand_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage: voice-sidecar ")
    assert "required: target" in captured.err
    assert captured.out == ""


def test_bench_tts_plays_through_the_output_device_and_closes_it(
    capsys: pytest.CaptureFixture[str], audio_device: list[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--voice", "fake:a"])

    assert audio_device == [
        "open 24000 1 int16",
        "start",
        "write 48000",
        "stop",
        "close",
    ]
    assert "ok" in capsys.readouterr().out


def test_bench_tts_with_no_play_never_touches_the_output_device(
    audio_device: list[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play"])

    assert audio_device == []


def test_bench_tts_closes_the_device_when_the_bench_raises(
    audio_device: list[str], spoken: list[str]
) -> None:
    with pytest.raises(KeyboardInterrupt):
        main(["bench", "tts", "--voice", "fake:a", "--voice", "fake:interrupt"])

    assert audio_device[-2:] == ["stop", "close"]


def test_bench_tts_usage_error_lists_the_known_providers(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    spoken: list[str],
) -> None:
    monkeypatch.setitem(TTS_PROVIDERS, "other", TTS_PROVIDERS["fake"])

    with pytest.raises(SystemExit):
        main(["bench", "tts", "--voice", "nope:fake"])

    assert "among fake, other" in capsys.readouterr().err


@pytest.fixture
def silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        TTS_PROVIDERS, "silent", TtsProvider(lambda options: SilentTts(), ("s",))
    )


def test_bench_tts_returns_normally_when_every_voice_is_ok(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play", "--voice", "fake:a"])

    captured = capsys.readouterr()
    assert "fake:a" in captured.out
    assert captured.err == ""


def test_bench_tts_returns_normally_when_one_voice_is_ok_and_one_skipped(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play", "--voice", "fake:gone", "--voice", "fake:a"])

    assert capsys.readouterr().err == ""


def test_bench_tts_exits_one_after_the_table_when_no_voice_is_ok(
    capsys: pytest.CaptureFixture[str], spoken: list[str], silent: None
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            ["bench", "tts", "--no-play", "--voice", "fake:gone", "--voice", "silent:s"]
        )

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert [line.split()[:2] for line in captured.out.splitlines()[1:]] == [
        ["fake:gone", "skipped"],
        ["silent:s", "failed"],
    ]
    assert captured.err == "voice-sidecar: no voice produced audio\n"


def test_bench_tts_exits_one_for_a_single_skipped_voice(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench", "tts", "--no-play", "--voice", "fake:gone"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out.splitlines()[1].split()[:2] == ["fake:gone", "skipped"]
    assert captured.err == "voice-sidecar: no voice produced audio\n"


def test_bench_tts_exits_one_for_a_single_failed_voice(
    capsys: pytest.CaptureFixture[str], spoken: list[str], silent: None
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench", "tts", "--no-play", "--voice", "silent:s"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out.splitlines()[1].split()[:2] == ["silent:s", "failed"]
    assert captured.err == "voice-sidecar: no voice produced audio\n"


def test_bench_tts_keeps_a_colon_inside_the_voice_name(
    capsys: pytest.CaptureFixture[str], spoken: list[str]
) -> None:
    main(["bench", "tts", "--no-play", "--voice", "fake:gone:x"])

    assert capsys.readouterr().out.splitlines()[1].split()[0] == "fake:gone:x"
    assert spoken == [DEFAULT_SENTENCE]


def test_bench_tts_blank_text_error_comes_from_the_bench_tts_parser(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench", "tts", "--no-play", "--voice", "say:Luciana", "--text", "  "])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage: voice-sidecar bench tts ")
    assert "voice-sidecar bench tts: error: the text must not be empty" in captured.err


@pytest.mark.parametrize(
    ("argv", "described"),
    [
        (["--help"], "compare providers by ear and by clock"),
        (["bench", "--help"], "speak one sentence in every voice"),
        (["bench", "tts", "--help"], "the sentence to speak"),
        (
            ["bench", "tts", "--help"],
            "provider:voice[@model] to bench; repeatable; default is every known voice",
        ),
        (["bench", "tts", "--help"], "time the voices without playing them"),
    ],
)
def test_help_describes_each_command_and_option(
    capsys: pytest.CaptureFixture[str], argv: list[str], described: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert re.search(rf"(^|\s){re.escape(described)}(\s|$)", text)


@pytest.fixture(autouse=True)
def no_system_proxy_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The macOS proxy lookup aborts in a forked worker; fail loudly instead."""

    def refuse() -> dict[str, str]:
        raise AssertionError(
            "a test built an httpx client that reads the system proxies"
        )

    monkeypatch.setattr("httpx._utils.getproxies", refuse)


@pytest.fixture
def served_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, bytes]:
    """Every pinned file name served from memory, with a cache root under tmp_path."""
    bodies = {
        name: f"body of {name}".encode()
        for files in models.PINS.values()
        for name in files
    }
    pins = {
        engine: {
            name: models.Pin(
                len(bodies[name]),
                hashlib.sha256(bodies[name]).hexdigest(),
                f"https://models.test/{engine}/{name}",
            )
            for name in files
        }
        for engine, files in models.PINS.items()
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bodies[request.url.path.rsplit("/", 1)[-1]])

    monkeypatch.setattr(models, "PINS", pins)
    monkeypatch.setattr(
        models,
        "make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return bodies


def test_models_fetch_kokoro_prints_one_line_per_file_and_exits_zero(
    capsys: pytest.CaptureFixture[str], served_models: dict[str, bytes], tmp_path: Path
) -> None:
    main(["models", "fetch", "kokoro"])

    assert capsys.readouterr().out.splitlines() == [
        "kokoro  kokoro-v1.0.onnx  fetched",
        "kokoro  voices-v1.0.bin  fetched",
    ]
    stored = tmp_path / "claude-voice" / "models" / "kokoro" / "voices-v1.0.bin"
    assert stored.read_bytes() == served_models["voices-v1.0.bin"]


def test_models_fetch_two_engines_prints_eight_lines_in_order(
    capsys: pytest.CaptureFixture[str], served_models: dict[str, bytes]
) -> None:
    main(["models", "fetch", "kokoro", "piper"])

    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ")[:2] for line in lines] == [
        ["kokoro", "kokoro-v1.0.onnx"],
        ["kokoro", "voices-v1.0.bin"],
        ["piper", "pt_BR-faber-medium.onnx"],
        ["piper", "pt_BR-faber-medium.onnx.json"],
        ["piper", "pt_BR-cadu-medium.onnx"],
        ["piper", "pt_BR-cadu-medium.onnx.json"],
        ["piper", "pt_BR-jeff-medium.onnx"],
        ["piper", "pt_BR-jeff-medium.onnx.json"],
    ]
    assert all(line.endswith("  fetched") for line in lines)


def test_models_fetch_reports_present_on_a_second_run(
    capsys: pytest.CaptureFixture[str], served_models: dict[str, bytes]
) -> None:
    main(["models", "fetch", "kokoro"])
    capsys.readouterr()
    main(["models", "fetch", "kokoro"])

    assert capsys.readouterr().out.splitlines() == [
        "kokoro  kokoro-v1.0.onnx  present",
        "kokoro  voices-v1.0.bin  present",
    ]


def test_models_fetch_with_one_bad_body_prints_every_line_and_exits_one(
    capsys: pytest.CaptureFixture[str],
    served_models: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "kokoro-v1.0.onnx":
            return httpx.Response(404)
        return httpx.Response(200, content=served_models[name])

    monkeypatch.setattr(
        models,
        "make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )
    with pytest.raises(SystemExit) as exit_info:
        main(["models", "fetch", "kokoro"])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.splitlines() == [
        "kokoro  kokoro-v1.0.onnx  failed  kokoro-v1.0.onnx: HTTP 404",
        "kokoro  voices-v1.0.bin  fetched",
    ]


def test_models_fetch_without_an_engine_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["models", "fetch"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "the following arguments are required: engine" in captured.err
    assert captured.out == ""


def test_models_fetch_with_an_unknown_engine_names_the_known_ones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["models", "fetch", "nope"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "invalid choice: 'nope' (choose from kokoro, piper)" in captured.err
    assert captured.out == ""


def test_models_without_a_subcommand_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["models"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "required: action" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("argv", "described"),
    [
        (["--help"], "manage the speech model files"),
        (["models", "--help"], "download an engine's pinned model files"),
        (["models", "fetch", "--help"], "the engine whose files to download"),
    ],
)
def test_help_describes_the_models_commands(
    capsys: pytest.CaptureFixture[str], argv: list[str], described: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert re.search(rf"(^|\s){re.escape(described)}(\s|$)", text)


def test_an_unknown_command_is_a_usage_error_naming_the_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["nope"])

    assert exit_info.value.code == 2
    assert "argument command: invalid choice: 'nope'" in capsys.readouterr().err


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_models_fetch_shows_progress_on_stderr_only_when_it_is_a_terminal(
    capsys: pytest.CaptureFixture[str],
    served_models: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = Terminal()
    monkeypatch.setattr(sys, "stderr", stderr)

    main(["models", "fetch", "kokoro"])

    shown = stderr.getvalue()
    assert "\r" in shown
    assert "kokoro  voices-v1.0.bin  100%" in shown
    assert "0.0 of 0.0 MB" in shown
    assert capsys.readouterr().out.splitlines() == [
        "kokoro  kokoro-v1.0.onnx  fetched",
        "kokoro  voices-v1.0.bin  fetched",
    ]


def test_models_fetch_progress_shows_megabytes_done_of_total(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    body = b"z" * 2_500_000
    monkeypatch.setattr(
        models,
        "PINS",
        {
            "kokoro": {
                "big.bin": models.Pin(
                    len(body), hashlib.sha256(body).hexdigest(), "https://models.test/b"
                )
            }
        },
    )
    monkeypatch.setattr(
        models,
        "make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
            trust_env=False,
        ),
    )
    stderr = Terminal()
    monkeypatch.setattr(sys, "stderr", stderr)

    main(["models", "fetch", "kokoro"])

    assert "kokoro  big.bin  100%  2.5 of 2.5 MB" in stderr.getvalue()


def test_models_fetch_clears_the_progress_line_before_each_result(
    served_models: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    stderr = Terminal()
    monkeypatch.setattr(sys, "stderr", stderr)

    main(["models", "fetch", "kokoro"])

    assert stderr.getvalue().endswith("\r\x1b[K")


def test_models_fetch_keeps_stderr_empty_when_it_is_not_a_terminal(
    capsys: pytest.CaptureFixture[str], served_models: dict[str, bytes]
) -> None:
    main(["models", "fetch", "kokoro", "piper"])

    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 8


class Stdout(io.StringIO):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def write(self, text: str, /) -> int:
        if "fetched" in text:
            self.events.append(f"line {text.strip()}")
        return super().write(text)

    def flush(self) -> None:
        self.events.append("flush")
        super().flush()


def test_models_fetch_prints_each_result_as_soon_as_its_file_ends(
    served_models: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        events.append(f"request {name}")
        return httpx.Response(200, content=served_models[name])

    monkeypatch.setattr(
        models,
        "make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )
    monkeypatch.setattr(sys, "stdout", Stdout(events))

    main(["models", "fetch", "kokoro"])

    significant = [e for e in events if e != "flush"]
    assert significant == [
        "request kokoro-v1.0.onnx",
        "line kokoro  kokoro-v1.0.onnx  fetched",
        "request voices-v1.0.bin",
        "line kokoro  voices-v1.0.bin  fetched",
    ]
    assert events.count("flush") >= 2


def test_models_fetch_reports_a_redirect_without_a_location_and_goes_on(
    capsys: pytest.CaptureFixture[str],
    served_models: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "kokoro-v1.0.onnx":
            return httpx.Response(302)
        return httpx.Response(200, content=served_models[name])

    monkeypatch.setattr(
        models,
        "make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )
    with pytest.raises(SystemExit) as exit_info:
        main(["models", "fetch", "kokoro"])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.splitlines() == [
        "kokoro  kokoro-v1.0.onnx  failed  "
        "kokoro-v1.0.onnx: HTTP 302 without a Location header",
        "kokoro  voices-v1.0.bin  fetched",
    ]


@pytest.fixture
def received(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    options_seen: list[dict[str, str]] = []

    def recording(options: Mapping[str, str]) -> TextToSpeech:
        options_seen.append(dict(options))
        return SpokenTts([])

    voices = {name: TTS_PROVIDERS[name].default_voices for name in TTS_PROVIDERS}
    for name in voices:
        monkeypatch.delitem(TTS_PROVIDERS, name)
    for name in ("say", "kokoro", "piper"):
        monkeypatch.setitem(TTS_PROVIDERS, name, TtsProvider(recording, voices[name]))
    monkeypatch.setitem(
        TTS_PROVIDERS, "fake", TtsProvider(recording, ("v",), ("m1", "m2"))
    )
    return options_seen


def bench_labels(capsys: pytest.CaptureFixture[str]) -> list[str]:
    lines = capsys.readouterr().out.splitlines()[1:]
    return [line.split()[0] for line in lines]


@pytest.mark.parametrize(
    ("spec", "options"),
    [
        ("fake:v@m2", {"voice": "v", "model": "m2"}),
        ("fake:v", {"voice": "v", "model": "m1"}),
        ("fake:a:b@m2", {"voice": "a:b", "model": "m2"}),
        ("fake:x@y@m2", {"voice": "x@y", "model": "m2"}),
        ("fake:v@other", {"voice": "v", "model": "other"}),
    ],
)
def test_bench_tts_passes_the_chosen_model_to_the_adapter(
    capsys: pytest.CaptureFixture[str],
    received: list[dict[str, str]],
    spec: str,
    options: dict[str, str],
) -> None:
    main(["bench", "tts", "--no-play", "--voice", spec])

    assert received == [options]
    assert bench_labels(capsys) == [f"fake:{options['voice']}@{options['model']}"]


def test_bench_tts_runs_every_default_voice_with_every_default_model(
    capsys: pytest.CaptureFixture[str], received: list[dict[str, str]]
) -> None:
    main(["bench", "tts", "--no-play"])

    assert bench_labels(capsys) == [
        "say:Luciana",
        "kokoro:pf_dora",
        "kokoro:pm_alex",
        "piper:faber",
        "piper:cadu",
        "piper:jeff",
        "fake:v@m1",
        "fake:v@m2",
    ]
    assert received == [
        {"voice": "Luciana"},
        {"voice": "pf_dora"},
        {"voice": "pm_alex"},
        {"voice": "faber"},
        {"voice": "cadu"},
        {"voice": "jeff"},
        {"voice": "v", "model": "m1"},
        {"voice": "v", "model": "m2"},
    ]


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ("fake:v@", "the model must not be empty"),
        ("say:Luciana@m1", "provider 'say' takes no model"),
        ("fake:@m1", "the voice must not be empty"),
        ("fake:", "expected provider:voice"),
        ("nope:v", "among fake, kokoro, piper, say"),
    ],
)
def test_bench_tts_rejects_a_bad_model_spec(
    capsys: pytest.CaptureFixture[str],
    received: list[dict[str, str]],
    spec: str,
    reason: str,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["bench", "tts", "--voice", spec])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert f"invalid voice {spec!r}" in captured.err
    assert reason in captured.err
    if "@" in spec:
        assert captured.err.endswith(f"invalid voice {spec!r}: {reason}\n")
    assert captured.out == ""
    assert received == []
