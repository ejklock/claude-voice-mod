import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import BinaryIO, Literal

import httpx

MAX_REDIRECTS = 5
_UMASK_LOCK = threading.Lock()

_KOKORO = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
)
_PIPER = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/"
    "c10ece1aade47bb51c153c893d14e5bf8e5b7117/pt/pt_BR"
)


@dataclass(frozen=True)
class Pin:
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class FetchResult:
    engine: str
    name: str
    outcome: Literal["fetched", "present", "replaced", "failed"]
    reason: str | None


PINS: dict[str, dict[str, Pin]] = {
    "kokoro": {
        "kokoro-v1.0.onnx": Pin(
            325505369,
            "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
            f"{_KOKORO}/kokoro-v1.0.onnx",
        ),
        "voices-v1.0.bin": Pin(
            28214398,
            "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
            f"{_KOKORO}/voices-v1.0.bin",
        ),
    },
    "piper": {
        "pt_BR-faber-medium.onnx": Pin(
            63201294,
            "858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7",
            f"{_PIPER}/faber/medium/pt_BR-faber-medium.onnx",
        ),
        "pt_BR-faber-medium.onnx.json": Pin(
            4855,
            "7e694de195ae3fc36dd732c445eb04fb49b649854893cb5506b978f0d50a1d6f",
            f"{_PIPER}/faber/medium/pt_BR-faber-medium.onnx.json",
        ),
        "pt_BR-cadu-medium.onnx": Pin(
            62950044,
            "765f0809a6ea9035d4a6d0d008dbf8876e68b2dd32029312672fa8f405bdb535",
            f"{_PIPER}/cadu/medium/pt_BR-cadu-medium.onnx",
        ),
        "pt_BR-cadu-medium.onnx.json": Pin(
            5040,
            "5fe03aa3d4901880554905b12075713cd552598c8a350455a1ec73f8b4e6be19",
            f"{_PIPER}/cadu/medium/pt_BR-cadu-medium.onnx.json",
        ),
        "pt_BR-jeff-medium.onnx": Pin(
            62950044,
            "3a6f4c46355813c2b7bbc4d16b6d13d60ed72074b952a393baace82a7d0c94b5",
            f"{_PIPER}/jeff/medium/pt_BR-jeff-medium.onnx",
        ),
        "pt_BR-jeff-medium.onnx.json": Pin(
            5041,
            "7bf8145b572b36806f5ce0f1d3322b6711975bc7d0473e8d36fced4a9ec0030d",
            f"{_PIPER}/jeff/medium/pt_BR-jeff-medium.onnx.json",
        ),
    },
}


class UnknownModel(LookupError):
    """The engine or file is not in the pin table; the message lists the known ones."""


class _Rejected(Exception):
    """A download that must not be kept; the message is the one-line reason."""


def engines() -> list[str]:
    return list(PINS)


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "claude-voice" / "models"


def model_path(engine: str, name: str, root: Path | None = None) -> Path:
    files = _engine_files(engine)
    if name not in files:
        known = ", ".join(files)
        raise UnknownModel(f"unknown {engine} file {name!r}; known files: {known}")
    return (cache_root() if root is None else root) / engine / name


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    )


def fetch_engine(
    engine: str,
    client: httpx.Client,
    root: Path,
    progress: Callable[[str, int, int], None] | None = None,
    on_result: Callable[[FetchResult], None] | None = None,
) -> list[FetchResult]:
    results: list[FetchResult] = []
    for name, pin in _engine_files(engine).items():
        report = None if progress is None else partial(progress, name)
        result = _fetch_file(engine, name, pin, client, root / engine, report)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def _engine_files(engine: str) -> dict[str, Pin]:
    if engine not in PINS:
        known = ", ".join(PINS)
        raise UnknownModel(f"unknown engine {engine!r}; known engines: {known}")
    return PINS[engine]


def _fetch_file(
    engine: str,
    name: str,
    pin: Pin,
    client: httpx.Client,
    folder: Path,
    report: Callable[[int, int], None] | None,
) -> FetchResult:
    final = folder / name
    try:
        if final.is_dir() and not final.is_symlink():
            raise _Rejected(f"{final} is a directory")
        if _matches(final, pin):
            return FetchResult(engine, name, "present", None)
        existed = final.exists() or final.is_symlink()
        folder.mkdir(parents=True, exist_ok=True)
        _download(client, pin, folder, final, report)
    except _Rejected as error:
        return FetchResult(engine, name, "failed", f"{name}: {error}")
    except (httpx.HTTPError, httpx.InvalidURL, OSError) as error:
        return FetchResult(
            engine, name, "failed", f"{name}: {str(error) or type(error).__name__}"
        )
    return FetchResult(engine, name, "replaced" if existed else "fetched", None)


def _matches(path: Path, pin: Pin) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != pin.size:
        return False
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest() == pin.sha256


def _new_file_mode() -> int:
    # os.umask can only be read by setting it; the lock keeps two fetch threads
    # from restoring each other's temporary value.
    with _UMASK_LOCK:
        mask = os.umask(0)
        os.umask(mask)
    return 0o666 & ~mask


def _download(
    client: httpx.Client,
    pin: Pin,
    folder: Path,
    final: Path,
    report: Callable[[int, int], None] | None,
) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=folder, prefix=f".{final.name}.", suffix=".part"
    )
    try:
        os.fchmod(descriptor, _new_file_mode())
        with os.fdopen(descriptor, "wb") as handle:
            _stream(client, pin, handle, report)
        os.replace(temporary, final)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _stream(
    client: httpx.Client,
    pin: Pin,
    handle: BinaryIO,
    report: Callable[[int, int], None] | None,
) -> None:
    url = pin.url
    for _ in range(MAX_REDIRECTS + 1):
        with client.stream("GET", url) as response:
            if response.has_redirect_location:
                url = str(response.request.url.join(response.headers["location"]))
                if not url.startswith("https://"):
                    raise _Rejected(f"redirect to {url} is not https")
                continue
            if 300 <= response.status_code < 400:
                raise _Rejected(
                    f"HTTP {response.status_code} without a Location header"
                )
            if response.status_code != 200:
                raise _Rejected(f"HTTP {response.status_code}")
            _consume(response, pin, handle, report)
            return
    raise _Rejected("too many redirects")


def _consume(
    response: httpx.Response,
    pin: Pin,
    handle: BinaryIO,
    report: Callable[[int, int], None] | None,
) -> None:
    digest = hashlib.sha256()
    received = 0
    step = max(1, pin.size // 100)
    reported = 0
    for chunk in response.iter_bytes():
        received += len(chunk)
        if received > pin.size:
            raise _Rejected(f"larger than the pinned {pin.size} bytes")
        digest.update(chunk)
        handle.write(chunk)
        if report is not None and (
            received // step > reported // step or received == pin.size
        ):
            reported = received
            report(received, pin.size)
    if received != pin.size:
        raise _Rejected(f"{received} bytes, expected {pin.size}")
    if digest.hexdigest() != pin.sha256:
        raise _Rejected(f"sha256 is {digest.hexdigest()}, expected {pin.sha256}")
