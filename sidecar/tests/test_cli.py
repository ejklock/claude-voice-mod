import shutil
import subprocess
import sys
from pathlib import Path


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
