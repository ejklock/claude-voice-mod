import hashlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from voice_sidecar import models
from voice_sidecar.models import (
    FetchResult,
    Pin,
    UnknownModel,
    cache_root,
    fetch_engine,
    make_client,
    model_path,
)

GOOD = b"good model bytes"
OTHER = b"other model bytes"


def pin_for(body: bytes, name: str, engine: str = "toy") -> Pin:
    return Pin(
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        url=f"https://models.test/{engine}/{name}",
    )


@pytest.fixture(autouse=True)
def no_system_proxy_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The macOS proxy lookup aborts in a forked worker; fail loudly instead."""

    def refuse() -> dict[str, str]:
        raise AssertionError(
            "a test built an httpx client that reads the system proxies"
        )

    monkeypatch.setattr("httpx._utils.getproxies", refuse)


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    bodies = {"a.bin": GOOD, "b.bin": OTHER}
    monkeypatch.setattr(
        models, "PINS", {"toy": {name: pin_for(b, name) for name, b in bodies.items()}}
    )
    return bodies


def serving(
    bodies: dict[str, bytes], requests: list[httpx.Request] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=bodies[name])

    return client_with(httpx.MockTransport(handler))


class Lazy(httpx.SyncByteStream):
    """A body produced chunk by chunk as the client reads it."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        return self.chunks


def client_with(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, trust_env=False)


def only_file_names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_cache_root_follows_xdg_cache_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache_root() == tmp_path / "claude-voice" / "models"


def test_without_xdg_cache_home_the_cache_still_lands_in_the_test_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME")

    assert cache_root().is_relative_to(tmp_path)


def test_the_guarded_cache_root_is_the_private_cache_directory(
    tmp_path: Path,
) -> None:
    assert cache_root() == tmp_path / "cache" / "claude-voice" / "models"


def test_cache_root_defaults_under_the_home_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cache_root() == tmp_path / ".cache" / "claude-voice" / "models"


def test_cache_root_defaults_under_the_home_when_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cache_root() == tmp_path / ".cache" / "claude-voice" / "models"


@pytest.mark.parametrize(
    ("engine", "names"),
    [
        ("kokoro", ["kokoro-v1.0.onnx", "voices-v1.0.bin"]),
        (
            "piper",
            [
                "pt_BR-faber-medium.onnx",
                "pt_BR-faber-medium.onnx.json",
                "pt_BR-cadu-medium.onnx",
                "pt_BR-cadu-medium.onnx.json",
                "pt_BR-jeff-medium.onnx",
                "pt_BR-jeff-medium.onnx.json",
            ],
        ),
    ],
)
def test_model_path_resolves_every_pinned_file_into_its_engine_folder(
    engine: str, names: list[str], tmp_path: Path
) -> None:
    assert list(models.PINS[engine]) == names
    for name in names:
        assert model_path(engine, name, tmp_path) == tmp_path / engine / name


def test_model_path_defaults_to_the_cache_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert model_path("kokoro", "voices-v1.0.bin") == (
        tmp_path / "claude-voice" / "models" / "kokoro" / "voices-v1.0.bin"
    )


def test_model_path_does_not_need_the_file_to_exist(tmp_path: Path) -> None:
    assert not model_path("kokoro", "voices-v1.0.bin", tmp_path).exists()


def test_model_path_for_an_unknown_engine_names_it_and_the_known_ones(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnknownModel) as raised:
        model_path("nope", "x.bin", tmp_path)
    assert str(raised.value) == "unknown engine 'nope'; known engines: kokoro, piper"


def test_model_path_for_an_unknown_file_names_it_and_the_known_ones(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnknownModel) as raised:
        model_path("kokoro", "x.bin", tmp_path)
    assert str(raised.value) == (
        "unknown kokoro file 'x.bin'; known files: kokoro-v1.0.onnx, voices-v1.0.bin"
    )


def test_pins_are_https_with_a_sha256_digest_and_a_size() -> None:
    for files in models.PINS.values():
        for pin in files.values():
            assert pin.url.startswith("https://")
            assert len(pin.sha256) == 64
            assert pin.size > 0


def test_a_fresh_fetch_writes_each_file_and_reports_fetched(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    results = fetch_engine("toy", serving(catalog), tmp_path)
    assert results == [
        FetchResult("toy", "a.bin", "fetched", None),
        FetchResult("toy", "b.bin", "fetched", None),
    ]
    assert (tmp_path / "toy" / "a.bin").read_bytes() == GOOD
    assert (tmp_path / "toy" / "b.bin").read_bytes() == OTHER
    assert only_file_names(tmp_path / "toy") == ["a.bin", "b.bin"]


def test_a_second_fetch_sends_no_request_and_reports_present(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    fetch_engine("toy", serving(catalog), tmp_path)
    requests: list[httpx.Request] = []
    results = fetch_engine("toy", serving(catalog, requests), tmp_path)
    assert [r.outcome for r in results] == ["present", "present"]
    assert requests == []


def test_a_corrupted_file_is_downloaded_again_and_reports_replaced(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    fetch_engine("toy", serving(catalog), tmp_path)
    (tmp_path / "toy" / "a.bin").write_bytes(b"x" * len(GOOD))
    results = fetch_engine("toy", serving(catalog), tmp_path)
    assert [r.outcome for r in results] == ["replaced", "present"]
    assert (tmp_path / "toy" / "a.bin").read_bytes() == GOOD


def test_an_existing_file_of_the_wrong_size_is_replaced(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    (tmp_path / "toy").mkdir()
    (tmp_path / "toy" / "a.bin").write_bytes(GOOD + b"!")
    results = fetch_engine("toy", serving(catalog), tmp_path)
    assert results[0].outcome == "replaced"
    assert (tmp_path / "toy" / "a.bin").read_bytes() == GOOD


def test_a_body_with_another_digest_fails_naming_the_file_and_both_digests(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    forged = b"X" * len(GOOD)
    bodies = {**catalog, "a.bin": forged}
    results = fetch_engine("toy", serving(bodies), tmp_path)
    expected = hashlib.sha256(GOOD).hexdigest()
    actual = hashlib.sha256(forged).hexdigest()
    assert results[0] == FetchResult(
        "toy",
        "a.bin",
        "failed",
        f"a.bin: sha256 is {actual}, expected {expected}",
    )
    assert only_file_names(tmp_path / "toy") == ["b.bin"]


def test_a_body_longer_than_the_pin_fails_as_soon_as_it_passes_the_size(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    sent: list[int] = []

    def endless() -> Iterator[bytes]:
        for index in range(1000):
            sent.append(index)
            yield b"y" * len(GOOD)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(200, stream=Lazy(endless()))
        return httpx.Response(200, content=OTHER)

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert results[0] == FetchResult(
        "toy", "a.bin", "failed", f"a.bin: larger than the pinned {len(GOOD)} bytes"
    )
    assert len(sent) < 10
    assert only_file_names(tmp_path / "toy") == ["b.bin"]


def test_a_body_shorter_than_the_pin_fails(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    bodies = {**catalog, "a.bin": GOOD[:-1]}
    results = fetch_engine("toy", serving(bodies), tmp_path)
    assert results[0] == FetchResult(
        "toy",
        "a.bin",
        "failed",
        f"a.bin: {len(GOOD) - 1} bytes, expected {len(GOOD)}",
    )
    assert only_file_names(tmp_path / "toy") == ["b.bin"]


def test_a_404_fails_naming_the_status(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    client = client_with(httpx.MockTransport(lambda r: httpx.Response(404)))
    results = fetch_engine("toy", client, tmp_path)
    assert results[0] == FetchResult("toy", "a.bin", "failed", "a.bin: HTTP 404")
    assert only_file_names(tmp_path / "toy") == []


def test_a_transport_error_mid_stream_fails_and_leaves_no_file(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def broken() -> Iterator[bytes]:
        yield GOOD[:4]
        raise httpx.ReadError("connection reset")

    client = client_with(
        httpx.MockTransport(lambda r: httpx.Response(200, stream=Lazy(broken())))
    )
    results = fetch_engine("toy", client, tmp_path)
    assert results[0] == FetchResult(
        "toy", "a.bin", "failed", "a.bin: connection reset"
    )
    assert only_file_names(tmp_path / "toy") == []


def test_a_transport_error_before_the_response_fails(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    results = fetch_engine("toy", client_with(httpx.MockTransport(refuse)), tmp_path)
    assert results[0].outcome == "failed"
    assert results[0].reason == "a.bin: timed out"


def test_an_https_redirect_is_followed(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/toy/a.bin":
            return httpx.Response(302, headers={"location": "https://cdn.test/blob"})
        return httpx.Response(
            200, content=GOOD if request.url.host == "cdn.test" else OTHER
        )

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert results[0].outcome == "fetched"
    assert (tmp_path / "toy" / "a.bin").read_bytes() == GOOD


def test_a_relative_redirect_is_followed_on_the_same_host(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/toy/a.bin":
            return httpx.Response(302, headers={"location": "/moved/a.bin"})
        return httpx.Response(
            200, content=GOOD if "a.bin" in request.url.path else OTHER
        )

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert [r.outcome for r in results] == ["fetched", "fetched"]


def test_an_http_redirect_target_fails_and_is_never_requested(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path.endswith("a.bin"):
            return httpx.Response(302, headers={"location": "http://cdn.test/blob"})
        return httpx.Response(200, content=OTHER)

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert results[0] == FetchResult(
        "toy", "a.bin", "failed", "a.bin: redirect to http://cdn.test/blob is not https"
    )
    assert "http://cdn.test/blob" not in requested
    assert only_file_names(tmp_path / "toy") == ["b.bin"]


def test_a_redirect_loop_fails(catalog: dict[str, bytes], tmp_path: Path) -> None:
    client = client_with(
        httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "https://models.test/x"})
        )
    )
    results = fetch_engine("toy", client, tmp_path)
    assert results[0] == FetchResult(
        "toy", "a.bin", "failed", "a.bin: too many redirects"
    )


def test_a_directory_at_the_final_path_fails_naming_it(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    (tmp_path / "toy" / "a.bin").mkdir(parents=True)
    requests: list[httpx.Request] = []
    results = fetch_engine("toy", serving(catalog, requests), tmp_path)
    assert results[0] == FetchResult(
        "toy",
        "a.bin",
        "failed",
        f"a.bin: {tmp_path / 'toy' / 'a.bin'} is a directory",
    )
    assert results[1].outcome == "fetched"
    assert (tmp_path / "toy" / "a.bin").is_dir()
    assert only_file_names(tmp_path / "toy") == ["a.bin", "b.bin"]


def test_a_cache_folder_that_cannot_be_created_fails_every_file(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    (tmp_path / "toy").write_bytes(b"in the way")
    results = fetch_engine("toy", serving(catalog), tmp_path)
    assert [r.outcome for r in results] == ["failed", "failed"]
    assert (tmp_path / "toy").read_bytes() == b"in the way"


def test_one_failing_file_does_not_stop_the_next(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(500)
        return httpx.Response(200, content=OTHER)

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert [r.outcome for r in results] == ["failed", "fetched"]
    assert (tmp_path / "toy" / "b.bin").read_bytes() == OTHER


def test_a_symlink_at_the_final_path_is_replaced_not_followed(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(GOOD)
    (tmp_path / "toy").mkdir()
    (tmp_path / "toy" / "a.bin").symlink_to(outside)
    results = fetch_engine("toy", serving(catalog), tmp_path)
    assert results[0].outcome == "replaced"
    assert not (tmp_path / "toy" / "a.bin").is_symlink()
    assert outside.read_bytes() == GOOD


def test_two_fetches_at_once_end_with_one_valid_file_and_no_temporary_file(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    barrier = threading.Barrier(2, timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            barrier.wait()
        return httpx.Response(200, content=catalog[request.url.path.rsplit("/", 1)[-1]])

    client = client_with(httpx.MockTransport(handler))
    outcomes: list[list[FetchResult]] = []

    def run() -> None:
        outcomes.append(fetch_engine("toy", client, tmp_path))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(outcomes) == 2
    assert all(r.outcome != "failed" for result in outcomes for r in result)
    assert only_file_names(tmp_path / "toy") == ["a.bin", "b.bin"]
    assert (tmp_path / "toy" / "a.bin").read_bytes() == GOOD


def test_unknown_engine_cannot_be_fetched(tmp_path: Path) -> None:
    with pytest.raises(UnknownModel):
        fetch_engine("nope", serving({}), tmp_path)


def test_the_client_bounds_connect_and_read_and_leaves_redirects_to_the_fetch() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    with make_client(transport) as client:
        assert client.follow_redirects is False
        assert client.timeout.connect == 10.0
        assert client.timeout.read == 30.0
        assert client.timeout.write == 30.0
        assert client.timeout.pool == 30.0
        assert client.get("https://models.test/x").status_code == 200


def test_a_client_without_an_injected_transport_would_read_the_system_proxies() -> None:
    with pytest.raises(AssertionError, match="system proxies"):
        make_client()


def test_the_temporary_file_lives_beside_the_final_one_until_the_download_ends(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    seen: list[list[str]] = []

    def body() -> Iterator[bytes]:
        seen.append(only_file_names(tmp_path / "toy"))
        yield GOOD

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(200, stream=Lazy(body()))
        return httpx.Response(200, content=OTHER)

    fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert len(seen) == 1
    assert len(seen[0]) == 1
    assert seen[0][0].startswith(".a.bin.")
    assert seen[0][0].endswith(".part")


def test_a_failure_reports_its_own_reason_when_the_temporary_file_is_already_gone(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def body() -> Iterator[bytes]:
        for leftover in (tmp_path / "toy").iterdir():
            leftover.unlink()
        yield b"z" * len(GOOD)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(200, stream=Lazy(body()))
        return httpx.Response(200, content=OTHER)

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert results[0].outcome == "failed"
    assert results[0].reason is not None
    assert results[0].reason.startswith("a.bin: sha256 is ")


def test_a_transport_error_without_a_message_names_its_type(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("")

    results = fetch_engine("toy", client_with(httpx.MockTransport(refuse)), tmp_path)
    assert results[0].reason == "a.bin: ReadError"


def test_every_request_is_a_get(catalog: dict[str, bytes], tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    fetch_engine("toy", serving(catalog, requests), tmp_path)
    assert [r.method for r in requests] == ["GET", "GET"]


def test_a_chain_of_the_allowed_number_of_redirects_is_followed(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        hop = request.url.path.rsplit("/", 1)[-1]
        if request.url.path == "/toy/b.bin":
            return httpx.Response(200, content=OTHER)
        if hop.startswith("hop"):
            number = int(hop.removeprefix("hop"))
            if number == models.MAX_REDIRECTS:
                return httpx.Response(200, content=GOOD)
            return httpx.Response(302, headers={"location": f"/hop{number + 1}"})
        return httpx.Response(302, headers={"location": "/hop1"})

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert results[0].outcome == "fetched"


def test_a_redirect_loop_stops_after_the_allowed_number_of_hops(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://models.test/x"})

    fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert len(requests) == 2 * (models.MAX_REDIRECTS + 1)


@pytest.mark.parametrize("status", [301, 302])
def test_a_redirect_without_a_location_fails_that_file_and_not_the_next(
    status: int, catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(status)
        return httpx.Response(200, content=OTHER)

    results = fetch_engine("toy", client_with(httpx.MockTransport(handler)), tmp_path)
    assert results == [
        FetchResult(
            "toy", "a.bin", "failed", f"a.bin: HTTP {status} without a Location header"
        ),
        FetchResult("toy", "b.bin", "fetched", None),
    ]
    assert only_file_names(tmp_path / "toy") == ["b.bin"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (300, "a.bin: HTTP 300 without a Location header"),
        (399, "a.bin: HTTP 399 without a Location header"),
        (400, "a.bin: HTTP 400"),
    ],
)
def test_only_a_3xx_status_is_reported_as_missing_its_location(
    status: int, reason: str, catalog: dict[str, bytes], tmp_path: Path
) -> None:
    client = client_with(httpx.MockTransport(lambda r: httpx.Response(status)))
    results = fetch_engine("toy", client, tmp_path)
    assert results[0].reason == reason


def test_progress_reports_every_byte_of_a_tiny_file_streamed_byte_by_byte(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(200, stream=Lazy(iter([bytes([b]) for b in GOOD])))
        return httpx.Response(200, content=OTHER)

    done: list[int] = []
    fetch_engine(
        "toy",
        client_with(httpx.MockTransport(handler)),
        tmp_path,
        progress=lambda name, count, total: (
            done.append(count) if name == "a.bin" else None
        ),
    )
    assert done == list(range(1, len(GOOD) + 1))


def test_a_file_under_a_hundred_steps_reports_every_chunk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = b"y" * 150
    monkeypatch.setattr(models, "PINS", {"toy": {"mid.bin": pin_for(body, "mid.bin")}})
    chunks = iter([bytes([c]) for c in body])
    client = client_with(
        httpx.MockTransport(lambda r: httpx.Response(200, stream=Lazy(chunks)))
    )
    done: list[int] = []
    fetch_engine(
        "toy", client, tmp_path, progress=lambda name, count, total: done.append(count)
    )
    assert done == list(range(1, 151))


def fetched_mode(catalog: dict[str, bytes], root: Path, umask: int) -> int:
    previous = os.umask(umask)
    try:
        fetch_engine("toy", serving(catalog), root)
    finally:
        os.umask(previous)
    return (root / "toy" / "a.bin").stat().st_mode & 0o777


def test_a_fetched_file_is_readable_like_a_normal_download(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    assert fetched_mode(catalog, tmp_path, 0o022) == 0o644


def test_a_fetched_file_honours_a_strict_umask(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    assert fetched_mode(catalog, tmp_path, 0o077) == 0o600


def test_reading_the_umask_leaves_it_unchanged(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    previous = os.umask(0o027)
    try:
        fetch_engine("toy", serving(catalog), tmp_path)
        assert os.umask(previous) == 0o027
    finally:
        os.umask(previous)


def test_a_present_file_keeps_its_mode(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    fetch_engine("toy", serving(catalog), tmp_path)
    (tmp_path / "toy" / "a.bin").chmod(0o640)
    fetch_engine("toy", serving({}), tmp_path)
    assert (tmp_path / "toy" / "a.bin").stat().st_mode & 0o777 == 0o640


def test_progress_reports_growing_counts_ending_at_the_pinned_size(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    parts = [GOOD[:5], GOOD[5:11], GOOD[11:]]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("a.bin"):
            return httpx.Response(200, stream=Lazy(iter(parts)))
        return httpx.Response(200, content=OTHER)

    calls: list[tuple[str, int, int]] = []
    fetch_engine(
        "toy",
        client_with(httpx.MockTransport(handler)),
        tmp_path,
        progress=lambda name, done, total: calls.append((name, done, total)),
    )
    assert [c for c in calls if c[0] == "a.bin"] == [
        ("a.bin", 5, 16),
        ("a.bin", 11, 16),
        ("a.bin", 16, 16),
    ]


def test_progress_is_throttled_to_about_one_call_per_percent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = b"x" * 10000
    monkeypatch.setattr(models, "PINS", {"toy": {"big.bin": pin_for(body, "big.bin")}})
    chunks = (body[i : i + 10] for i in range(0, len(body), 10))
    client = client_with(
        httpx.MockTransport(lambda r: httpx.Response(200, stream=Lazy(chunks)))
    )
    done: list[int] = []
    fetch_engine(
        "toy", client, tmp_path, progress=lambda name, count, total: done.append(count)
    )
    assert len(done) == 100
    assert done == sorted(done)
    assert done[-1] == 10000


def test_a_present_file_reports_no_progress(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    fetch_engine("toy", serving(catalog), tmp_path)
    calls: list[int] = []
    fetch_engine(
        "toy",
        serving({}),
        tmp_path,
        progress=lambda name, done, total: calls.append(done),
    )
    assert calls == []


def test_each_result_is_reported_before_the_next_file_is_requested(
    catalog: dict[str, bytes], tmp_path: Path
) -> None:
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        events.append(f"request {name}")
        return httpx.Response(200, content=catalog[name])

    results = fetch_engine(
        "toy",
        client_with(httpx.MockTransport(handler)),
        tmp_path,
        on_result=lambda result: events.append(f"result {result.name}"),
    )
    assert events == ["request a.bin", "result a.bin", "request b.bin", "result b.bin"]
    assert [r.name for r in results] == ["a.bin", "b.bin"]


def test_every_test_gets_a_private_cache_root_without_setting_one(
    tmp_path: Path,
) -> None:
    root = cache_root()
    assert root.is_relative_to(tmp_path)
    assert not root.is_relative_to(Path.home())
