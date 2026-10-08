import json
import os
import stat
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from conftest import (
    luciana_skip_reason,
    needs_say,
    needs_say_luciana,
    say_skip_reason,
)

from voice_sidecar.adapters.local.say import SayTts
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.providers import create_tts

FAKE_SAY = f"""#!{sys.executable}
import json, os, sys, wave

args = sys.argv[1:]
mode = os.environ.get("SAY_MODE", "ok")
if args[:2] == ["-v", "?"]:
    if mode == "listfail":
        sys.exit(1)
    print("Albert              en_US    # Hello! My name is Albert.")
    print("Luciana (Portuguese (Brazil)) pt_BR    # Ola # meu nome e Luciana.")
    print("Fiona               en-scotland    # Hello")
    print("this line has no locale column")
    sys.exit(0)
with open(os.environ["SAY_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
out = args[args.index("-o") + 1]
if mode == "fail":
    open(out, "w").close()
    sys.stderr.write("voice exploded\\n")
    sys.exit(3)
channels = 2 if mode == "stereo" else 1
width = 1 if mode == "8bit" else 2
with wave.open(out, "wb") as wav:
    wav.setnchannels(channels)
    wav.setsampwidth(width)
    wav.setframerate(24000)
    wav.writeframes(bytes(i % 256 for i in range(10000 * channels * width)))
"""


@pytest.fixture
def fake_say(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "say"
    script.write_text(FAKE_SAY, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "say.log"
    monkeypatch.setenv("SAY_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


@pytest.fixture
def scratch_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return scratch


def calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@needs_say_luciana
def test_synthesize_yields_24khz_pcm_of_even_length(scratch_tmp: Path) -> None:
    chunks = list(SayTts("Luciana").synthesize("Olá, mundo."))

    pcm = b"".join(chunk.pcm for chunk in chunks)
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0
    assert {chunk.sample_rate for chunk in chunks} == {24000}
    assert list(scratch_tmp.iterdir()) == []


@needs_say_luciana
def test_the_temporary_file_lives_in_a_named_directory_until_the_stream_closes(
    scratch_tmp: Path,
) -> None:
    stream = SayTts("Luciana").synthesize("Olá, mundo.")
    next(stream)
    assert isinstance(stream, Generator)

    [directory] = scratch_tmp.iterdir()
    assert directory.name.startswith("voice-say-")

    stream.close()
    assert list(scratch_tmp.iterdir()) == []


@needs_say
def test_a_voice_that_is_not_installed_is_unavailable_at_construction() -> None:
    with pytest.raises(ProviderUnavailable) as error:
        SayTts("NoSuchVoice")

    assert "NoSuchVoice" in error.value.reason


def test_synthesize_passes_voice_format_and_text_to_say_and_streams_the_audio(
    fake_say: Path, scratch_tmp: Path
) -> None:
    chunks = list(SayTts("Albert").synthesize("-olá"))

    [call] = calls(fake_say)
    assert call[:2] == ["-v", "Albert"]
    assert call[2] == "-o"
    assert call[4:] == ["--data-format=LEI16@24000", "--", "-olá"]
    assert [len(chunk.pcm) for chunk in chunks] == [9600, 9600, 800]
    assert {chunk.sample_rate for chunk in chunks} == {24000}
    assert b"".join(chunk.pcm for chunk in chunks) == bytes(
        i % 256 for i in range(20000)
    )
    assert list(scratch_tmp.iterdir()) == []


@pytest.mark.parametrize("mode", ["stereo", "8bit"])
def test_audio_that_is_not_mono_16_bit_is_an_error(
    fake_say: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("SAY_MODE", mode)

    with pytest.raises(RuntimeError) as error:
        list(SayTts("Albert").synthesize("olá"))

    assert str(error.value) == "say wrote audio that is not mono 16-bit"


def test_a_voice_missing_from_the_listing_is_unavailable(fake_say: Path) -> None:
    with pytest.raises(ProviderUnavailable) as error:
        SayTts("Albe")

    assert error.value.reason == "say has no voice 'Albe' installed"
    assert not fake_say.exists()


def test_a_voice_is_found_by_its_plain_name_or_its_qualified_name(
    fake_say: Path,
) -> None:
    assert SayTts("Albert").name == "say"
    assert SayTts("Luciana").voice == "Luciana"
    assert SayTts("Luciana (Portuguese (Brazil))").name == "say"


def test_a_voice_that_only_prefixes_an_installed_one_is_unavailable(
    fake_say: Path,
) -> None:
    with pytest.raises(ProviderUnavailable):
        SayTts("Lucian")


def test_a_failing_listing_means_no_voice_is_installed(
    fake_say: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAY_MODE", "listfail")

    with pytest.raises(ProviderUnavailable) as error:
        SayTts("Albert")

    assert error.value.reason == "say has no voice 'Albert' installed"


def test_a_missing_say_command_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ProviderUnavailable) as error:
        SayTts("Luciana")

    assert error.value.reason == "the say command is not installed"


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_blank_text_yields_nothing_and_runs_no_say(fake_say: Path, text: str) -> None:
    assert list(SayTts("Albert").synthesize(text)) == []
    assert not fake_say.exists()


def test_a_failing_say_reports_the_exit_code_and_stderr_and_leaves_no_file(
    fake_say: Path, scratch_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAY_MODE", "fail")

    with pytest.raises(RuntimeError) as error:
        list(SayTts("Albert").synthesize("olá"))

    assert str(error.value) == "say exited with code 3: voice exploded"
    assert len(calls(fake_say)) == 1
    assert list(scratch_tmp.iterdir()) == []


def test_the_registry_builds_the_say_adapter_with_the_given_voice(
    fake_say: Path,
) -> None:
    tts = create_tts("say", {"voice": "Albert"})

    assert isinstance(tts, SayTts)
    assert tts.voice == "Albert"


def test_the_registry_defaults_the_say_voice_to_luciana(fake_say: Path) -> None:
    tts = create_tts("say", {})

    assert isinstance(tts, SayTts)
    assert tts.voice == "Luciana"


def test_the_registry_refuses_an_unknown_provider() -> None:
    with pytest.raises(ProviderUnavailable) as error:
        create_tts("nope", {})

    assert str(error.value) == "unknown provider 'nope'"
    assert error.value.reason == "unknown provider 'nope'"


def test_the_marker_runs_the_tests_when_say_lists_luciana(fake_say: Path) -> None:
    assert luciana_skip_reason() is None


def test_the_marker_skips_naming_the_missing_say_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert luciana_skip_reason() == "the macOS say command is not installed"


def test_the_marker_skips_naming_the_missing_luciana_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "say"
    script.write_text(
        f"#!{sys.executable}\nprint('Albert              en_US    # Hello')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert luciana_skip_reason() == "the say voice Luciana is not installed"


def test_the_say_only_marker_skips_naming_the_missing_say_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert say_skip_reason() == "the macOS say command is not installed"


def test_the_say_only_marker_runs_the_tests_whatever_voices_are_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "say"
    script.write_text(
        f"#!{sys.executable}\nprint('Albert              en_US    # Hello')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert say_skip_reason() is None


def test_the_marker_skips_as_no_luciana_when_say_cannot_be_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "say"
    script.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert luciana_skip_reason() == "the say voice Luciana is not installed"


def test_the_marker_skips_as_no_luciana_when_the_listing_fails(
    fake_say: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAY_MODE", "listfail")

    assert luciana_skip_reason() == "the say voice Luciana is not installed"
