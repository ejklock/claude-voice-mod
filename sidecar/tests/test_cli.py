import shutil
import subprocess
import sys
from pathlib import Path

from conftest import needs_say_luciana


def run(*args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("voice-sidecar", path=str(Path(sys.executable).parent))
    assert executable is not None
    return subprocess.run(
        [executable, *args], capture_output=True, text=True, check=False
    )


def test_version_prints_the_plugin_version(plugin_version: str) -> None:
    result = run("--version")

    assert result.returncode == 0
    assert result.stdout == f"{plugin_version}\n"


def test_help_names_the_version_flag() -> None:
    result = run("--help")

    assert result.returncode == 0
    assert "--version" in result.stdout


def test_unknown_flag_is_a_usage_error() -> None:
    result = run("--bogus")

    assert result.returncode == 2
    assert result.stderr.startswith("usage:")
    assert result.stdout == ""


def test_no_argument_is_a_usage_error() -> None:
    result = run()

    assert result.returncode == 2
    assert result.stderr.startswith("usage:")
    assert result.stdout == ""


@needs_say_luciana
def test_bench_tts_without_playing_prints_a_say_row() -> None:
    result = run("bench", "tts", "--no-play", "--voice", "say:Luciana")

    lines = result.stdout.splitlines()
    assert result.returncode == 0
    assert len(lines) == 2
    assert lines[0].split()[:2] == ["voice", "status"]
    assert lines[1].split()[:2] == ["say:Luciana", "ok"]


def test_bench_tts_with_an_unknown_voice_is_a_usage_error() -> None:
    result = run("bench", "tts", "--voice", "nope:x")

    assert result.returncode == 2
    assert result.stderr.startswith("usage:")
    assert "nope:x" in result.stderr
    assert result.stdout == ""


def test_bench_tts_with_empty_text_is_a_usage_error() -> None:
    result = run("bench", "tts", "--text", "")

    assert result.returncode == 2
    assert result.stderr.startswith("usage:")
    assert "text" in result.stderr
    assert result.stdout == ""


def test_bench_without_a_subcommand_is_a_usage_error() -> None:
    result = run("bench")

    assert result.returncode == 2
    assert result.stderr.startswith("usage:")
    assert result.stdout == ""
