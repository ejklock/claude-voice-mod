import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import httpx
import pytest

MANIFEST = Path(".claude-plugin") / "plugin.json"


def find_plugin_json() -> Path:
    for directory in Path(__file__).resolve().parents:
        candidate = directory / MANIFEST
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no {MANIFEST} above {Path(__file__).resolve()}")


def say_skip_reason() -> str | None:
    """Why the real `say` command is unusable here, or None."""
    if shutil.which("say") is None:
        return "the macOS say command is not installed"
    return None


def luciana_skip_reason() -> str | None:
    """Why the real `say` with the Luciana voice is unusable here, or None."""
    missing_say = say_skip_reason()
    if missing_say is not None:
        return missing_say
    try:
        listing = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=False
        )
    except OSError:
        return "the say voice Luciana is not installed"
    names = [
        line.split(maxsplit=1)[0]
        for line in listing.stdout.splitlines()
        if line.strip()
    ]
    if listing.returncode != 0 or "Luciana" not in names:
        return "the say voice Luciana is not installed"
    return None


needs_say = pytest.mark.skipif(
    (_say_reason := say_skip_reason()) is not None, reason=_say_reason or ""
)

needs_say_luciana = pytest.mark.skipif(
    (_reason := luciana_skip_reason()) is not None, reason=_reason or ""
)


@pytest.fixture(scope="session")
def plugin_version() -> str:
    return str(json.loads(find_plugin_json().read_text(encoding="utf-8"))["version"])


SILENT_SOUNDDEVICE = """\
class RawOutputStream:
    def __init__(self, samplerate, channels, dtype):
        pass

    def start(self):
        pass

    def write(self, data):
        pass

    def stop(self):
        pass

    def close(self):
        pass
"""


@pytest.fixture(autouse=True)
def private_cache_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test reads or writes the user's real model cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


@pytest.fixture(autouse=True)
def no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits a provider key, so none can send a real request."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client built without a mock transport fails fast, never reaching the network.

    Any proxy variable makes urllib skip the macOS SystemConfiguration lookup,
    which aborts a process forked by mutmut.
    """
    monkeypatch.setenv("NO_PROXY", "*")

    def refuse(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise RuntimeError("tests must use httpx.MockTransport, never a real transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(autouse=True)
def audio_device(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> list[str]:
    """No test reaches a real output device; the log records what a fake one saw.

    In-process code gets a recording module; child processes get a silent one
    through PYTHONPATH.
    """
    log: list[str] = []

    class RawOutputStream:
        def __init__(self, samplerate: int, channels: int, dtype: str) -> None:
            log.append(f"open {samplerate} {channels} {dtype}")

        def start(self) -> None:
            log.append("start")

        def write(self, data: bytes) -> None:
            log.append(f"write {len(data)}")

        def stop(self) -> None:
            log.append("stop")

        def close(self) -> None:
            log.append("close")

    device = types.ModuleType("sounddevice")
    device.RawOutputStream = RawOutputStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", device)

    silent = tmp_path_factory.mktemp("silent-audio")
    (silent / "sounddevice.py").write_text(SILENT_SOUNDDEVICE, encoding="utf-8")
    inherited = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", f"{silent}{os.pathsep}{inherited}" if inherited else str(silent)
    )
    return log
