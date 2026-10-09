import json
import socket
import urllib.request
from collections.abc import Generator, Iterator
from typing import cast

import httpx
import pytest

from voice_sidecar import models
from voice_sidecar.adapters.external.openai import OpenAiTts
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk
from voice_sidecar.providers import create_tts

KEY = "TESTKEY"
URL = "https://api.openai.com/v1/audio/speech"


class Server:
    """A MockTransport that records requests and the clients built on it."""

    def __init__(self, response: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self.clients: list[httpx.Client] = []
        self._response = response

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture(autouse=True)
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", KEY)


def build(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response | Exception,
    voice: str = "marin",
    model: str = "gpt-4o-mini-tts",
) -> tuple[OpenAiTts, Server]:
    server = Server(response)
    real = models.make_client

    def spy(transport: httpx.BaseTransport | None = None) -> httpx.Client:
        client = real(httpx.MockTransport(server.handler))
        server.clients.append(client)
        return client

    monkeypatch.setattr(models, "make_client", spy)
    return OpenAiTts(voice, model), server


def streamed(*pieces: bytes) -> httpx.Response:
    return httpx.Response(200, content=iter(pieces))


def drain(tts: OpenAiTts, text: str = "hello") -> list[AudioChunk]:
    return list(tts.synthesize(text))


def test_sends_one_post_with_the_key_and_the_exact_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"), "echo", "gpt-x")

    drain(tts, "olá mundo")

    [request] = server.requests
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "model": "gpt-x",
        "input": "olá mundo",
        "voice": "echo",
        "response_format": "pcm",
    }
    assert tts.name == "openai"


def test_pieces_of_odd_size_yield_only_even_chunks_at_24khz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pieces = (b"\x01\x02\x03", b"\x04", b"\x05\x06\x07\x08")
    tts, _ = build(monkeypatch, streamed(*pieces))

    chunks = drain(tts)

    assert all(len(c.pcm) % 2 == 0 and c.pcm for c in chunks)
    assert {c.sample_rate for c in chunks} == {24000}
    assert b"".join(c.pcm for c in chunks) == b"".join(pieces)


def close(stream: Iterator[AudioChunk]) -> None:
    cast(Generator[AudioChunk, None, None], stream).close()


def test_first_chunk_is_yielded_before_the_body_is_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed: list[int] = []

    def body() -> Iterator[bytes]:
        for index in range(3):
            consumed.append(index)
            yield b"\x00\x01"

    tts, _ = build(monkeypatch, httpx.Response(200, content=body()))
    stream = tts.synthesize("hello")

    first = next(stream)

    assert first.pcm == b"\x00\x01"
    assert consumed == [0]
    close(stream)


def test_odd_total_length_raises_after_the_aligned_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, _ = build(monkeypatch, streamed(b"\x01\x02", b"\x03\x04\x05"))
    stream = tts.synthesize("hello")
    heard = b""

    with pytest.raises(RuntimeError) as raised:
        for chunk in stream:
            heard += chunk.pcm

    assert heard == b"\x01\x02\x03\x04"
    assert str(raised.value) == "openai returned audio with 1 odd byte"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_text_yields_nothing_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"))

    assert drain(tts, text) == []
    assert server.requests == []
    assert server.clients == []


def test_an_empty_body_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    tts, _ = build(monkeypatch, httpx.Response(200, content=b""))

    assert drain(tts) == []


def test_the_client_is_closed_when_the_stream_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"))

    drain(tts)

    [client] = server.clients
    assert client.is_closed


def test_the_client_is_closed_when_the_caller_closes_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab", b"cd"))
    stream = tts.synthesize("hello")
    next(stream)

    close(stream)

    [client] = server.clients
    assert client.is_closed


def test_the_client_is_closed_after_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tts, server = build(monkeypatch, httpx.Response(500, content=b"boom"))

    with pytest.raises(RuntimeError):
        drain(tts)

    [client] = server.clients
    assert client.is_closed


@pytest.mark.parametrize("value", [None, "", "   \n"])
def test_a_missing_key_is_unavailable_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("OPENAI_API_KEY")
    else:
        monkeypatch.setenv("OPENAI_API_KEY", value)
    server = Server(httpx.Response(200, content=b"ab"))
    monkeypatch.setattr(
        models, "make_client", lambda transport=None: pytest.fail("client built")
    )

    with pytest.raises(ProviderUnavailable) as raised:
        OpenAiTts("marin", "gpt-4o-mini-tts", httpx.MockTransport(server.handler))

    assert raised.value.reason == "OPENAI_API_KEY is not set"
    assert server.requests == []


def test_the_key_is_stripped_in_the_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", f"  {KEY}\n")
    tts, server = build(monkeypatch, streamed(b"ab"))

    drain(tts)

    assert server.requests[0].headers["Authorization"] == f"Bearer {KEY}"


def test_the_constructor_hands_its_transport_to_the_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.BaseTransport | None] = []

    def spy(transport: httpx.BaseTransport | None = None) -> httpx.Client:
        seen.append(transport)
        return httpx.Client(transport=transport or transport_in_use)

    monkeypatch.setattr(models, "make_client", spy)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"ab"))
    transport_in_use = httpx.MockTransport(lambda request: httpx.Response(200))

    drain(OpenAiTts("marin", "m", transport))

    assert seen == [transport]


def failure(status: int, body: bytes, content_type: str) -> httpx.Response:
    return httpx.Response(status, content=body, headers={"content-type": content_type})


def raised_message(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> str:
    tts, _ = build(monkeypatch, response)
    with pytest.raises(RuntimeError) as raised:
        drain(tts)
    return str(raised.value)


def test_a_401_that_echoes_the_key_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"error": {"message": f"Incorrect API key provided: {KEY}"}})

    message = raised_message(
        monkeypatch, failure(401, body.encode(), "application/json")
    )

    assert message == "openai returned HTTP 401: Incorrect API key provided: ***"
    assert KEY not in message


def test_a_text_403_keeps_only_the_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    message = raised_message(
        monkeypatch, failure(403, b"Forbidden\nmore", "text/plain")
    )

    assert message == "openai returned HTTP 403: Forbidden"


def test_a_400_json_message_reaches_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"error": {"message": "voice 'zzz' is not supported"}})

    message = raised_message(
        monkeypatch, failure(400, body.encode(), "application/json")
    )

    assert message == "openai returned HTTP 400: voice 'zzz' is not supported"


def test_a_long_error_body_is_cut_to_200_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = raised_message(monkeypatch, failure(500, b"x" * 10_000, "text/plain"))

    assert message == "openai returned HTTP 500: " + "x" * 200


def test_a_200_character_message_is_kept_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = raised_message(monkeypatch, failure(500, b"y" * 200, "text/plain"))

    assert message == "openai returned HTTP 500: " + "y" * 200


@pytest.mark.parametrize(
    "body", [b'{"detail": "nope"}', b'{"error": {"code": 7}}', b'{"error": "x"}']
)
def test_a_json_body_without_a_message_falls_back_to_the_text(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    message = raised_message(monkeypatch, failure(502, body, "application/json"))

    assert message == f"openai returned HTTP 502: {body.decode()}"


def test_a_json_array_body_falls_back_to_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = raised_message(monkeypatch, failure(500, b"[1]", "application/json"))

    assert message == "openai returned HTTP 500: [1]"


def test_a_json_message_keeps_only_its_first_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"error": {"message": "first\nsecond"}})

    message = raised_message(
        monkeypatch, failure(400, body.encode(), "application/json")
    )

    assert message == "openai returned HTTP 400: first"


def test_only_4096_bytes_of_an_error_body_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed: list[int] = []

    def body() -> Iterator[bytes]:
        for index in range(100):
            consumed.append(index)
            yield b"z" * 1024

    message = raised_message(monkeypatch, httpx.Response(500, content=body()))

    assert message == "openai returned HTTP 500: " + "z" * 200
    assert len(consumed) <= 5


def test_a_multibyte_error_body_never_raises_a_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "€".encode() * 2000

    message = raised_message(monkeypatch, failure(500, body, "text/plain"))

    assert message == "openai returned HTTP 500: " + "€" * 200


def test_an_error_body_of_exactly_4096_bytes_stops_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed: list[int] = []

    def body() -> Iterator[bytes]:
        for index in range(3):
            consumed.append(index)
            yield b"q" * 4096

    raised_message(monkeypatch, httpx.Response(500, content=body()))

    assert consumed == [0]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            failure(500, b"", "text/plain"),
            "openai returned HTTP 500: Internal Server Error",
        ),
        (
            failure(503, b"  \n  ", "text/plain"),
            "openai returned HTTP 503: Service Unavailable",
        ),
        (
            failure(401, b'{"error": {"message": ""}}', "application/json"),
            "openai returned HTTP 401: Unauthorized",
        ),
        (failure(599, b"", "text/plain"), "openai returned HTTP 599"),
        (failure(500, b"boom", "text/plain"), "openai returned HTTP 500: boom"),
    ],
)
def test_an_error_without_a_usable_message_falls_back_to_the_reason(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, expected: str
) -> None:
    assert raised_message(monkeypatch, response) == expected


def test_the_registry_builds_the_adapter_from_its_options() -> None:
    tts = create_tts("openai", {"voice": "echo", "model": "gpt-x"})
    default = create_tts("openai", {})

    assert isinstance(tts, OpenAiTts)
    assert isinstance(default, OpenAiTts)
    assert (tts.voice, tts.model) == ("echo", "gpt-x")
    assert (default.voice, default.model) == ("marin", "gpt-4o-mini-tts")


def test_a_redirect_is_an_error_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(302, headers={"location": "https://evil.example/"})

    message = raised_message(monkeypatch, response)

    assert message.startswith("openai returned HTTP 302")


def test_a_connection_failure_does_not_leak_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, _ = build(monkeypatch, httpx.ConnectError("connection refused"))

    with pytest.raises(httpx.ConnectError) as raised:
        drain(tts)

    assert KEY not in str(raised.value)


def test_a_client_without_a_mock_transport_fails_fast_and_opens_no_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[object] = []
    monkeypatch.setattr(
        socket.socket, "connect", lambda self, address: opened.append(address)
    )

    with (
        models.make_client() as client,
        pytest.raises(RuntimeError, match=r"httpx\.MockTransport"),
    ):
        client.get(URL)

    assert opened == []


def test_the_adapter_without_a_mock_transport_fails_fast_on_synthesize() -> None:
    tts = OpenAiTts("marin", "m")

    with pytest.raises(RuntimeError, match=r"httpx\.MockTransport"):
        drain(tts)


def test_building_a_client_never_asks_the_macos_proxy_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def lookup() -> dict[str, str]:
        calls.append(1)
        return {}

    monkeypatch.setattr(
        urllib.request, "getproxies_macosx_sysconf", lookup, raising=False
    )

    models.make_client().close()

    assert calls == []
