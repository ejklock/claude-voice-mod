import json
from collections.abc import Callable, Generator, Iterator
from typing import Any, cast

import httpx
import pytest

from voice_sidecar import models
from voice_sidecar.adapters.external.elevenlabs import ElevenLabsTts
from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import AudioChunk
from voice_sidecar.providers import create_tts

KEY = "TESTKEY"
BASE = "https://api.elevenlabs.io"
Handler = Callable[[httpx.Request], httpx.Response]


class Server:
    """A MockTransport that records requests and the clients built on it."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self.clients: list[httpx.Client] = []
        self._handler = handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def posts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST"]

    def gets(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "GET" and r.url.path == path]


@pytest.fixture(autouse=True)
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)


def install(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> Server:
    server = Server(handler)
    real = models.make_client

    def spy(transport: httpx.BaseTransport | None = None) -> httpx.Client:
        client = real(httpx.MockTransport(server.handle))
        server.clients.append(client)
        return client

    monkeypatch.setattr(models, "make_client", spy)
    return server


def build(
    monkeypatch: pytest.MonkeyPatch,
    handler: Handler,
    voice: str = "abc123",
    model: str = "eleven_flash_v2_5",
) -> tuple[ElevenLabsTts, Server]:
    server = install(monkeypatch, handler)
    return ElevenLabsTts(voice, model), server


def streamed(*pieces: bytes) -> Handler:
    return lambda request: httpx.Response(200, content=iter(pieces))


def drain(tts: ElevenLabsTts, text: str = "hello") -> list[AudioChunk]:
    return list(tts.synthesize(text))


def close(stream: Iterator[AudioChunk]) -> None:
    cast(Generator[AudioChunk, None, None], stream).close()


def json_response(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def voice(
    voice_id: str,
    locale: str | None = None,
    language: str | None = None,
    accent: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if locale is not None:
        entry["locale"] = locale
    if language is not None:
        entry["language"] = language
    if accent is not None:
        entry["accent"] = accent
    return {"voice_id": voice_id, "name": voice_id, "verified_languages": [entry]}


def listing(
    voices: list[Any], has_more: bool = False, token: str | None = None
) -> httpx.Response:
    return json_response(
        {"voices": voices, "has_more": has_more, "next_page_token": token}
    )


def account(voices: list[Any]) -> Handler:
    return lambda request: listing(voices)


def resolved(monkeypatch: pytest.MonkeyPatch, voices: list[Any]) -> str:
    """The voice id `auto` resolves to, read from the request synthesis sends."""
    tts, server = build(monkeypatch, auto_handler(voices), "auto")
    drain(tts)
    [post] = server.posts()
    return post.url.raw_path.decode().split("/")[3]


def auto_handler(voices: list[Any]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return listing(voices)
        return httpx.Response(200, content=b"ab")

    return handler


def unavailable(
    monkeypatch: pytest.MonkeyPatch, handler: Handler, voice_name: str = "auto"
) -> str:
    install(monkeypatch, handler)
    with pytest.raises(ProviderUnavailable) as raised:
        ElevenLabsTts(voice_name, "eleven_flash_v2_5")
    return raised.value.reason


# C1 key


@pytest.mark.parametrize("value", [None, "", "   \n"])
@pytest.mark.parametrize("voice_name", ["auto", "abc123"])
def test_a_missing_key_is_unavailable_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, value: str | None, voice_name: str
) -> None:
    if value is None:
        monkeypatch.delenv("ELEVENLABS_API_KEY")
    else:
        monkeypatch.setenv("ELEVENLABS_API_KEY", value)
    server = Server(lambda request: httpx.Response(200))
    monkeypatch.setattr(
        models, "make_client", lambda transport=None: pytest.fail("client built")
    )

    with pytest.raises(ProviderUnavailable) as raised:
        ElevenLabsTts(voice_name, "m", httpx.MockTransport(server.handle))

    assert raised.value.reason == "ELEVENLABS_API_KEY is not set"
    assert server.requests == []


def test_the_key_is_stripped_and_sent_only_in_its_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", f"  {KEY}\n")
    tts, server = build(monkeypatch, streamed(b"ab"))

    drain(tts, "olá")

    [request] = server.requests
    assert request.headers["xi-api-key"] == KEY
    assert KEY not in str(request.url)
    assert KEY not in request.content.decode()
    assert set(request.headers) & {"authorization"} == set()


def test_the_constructor_hands_its_transport_to_the_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.BaseTransport | None] = []
    inner = httpx.MockTransport(lambda request: listing([voice("v1", "pt-BR")]))

    def spy(transport: httpx.BaseTransport | None = None) -> httpx.Client:
        seen.append(transport)
        return httpx.Client(transport=inner)

    monkeypatch.setattr(models, "make_client", spy)
    transport = httpx.MockTransport(lambda request: httpx.Response(200))

    ElevenLabsTts("auto", "m", transport)

    assert seen == [transport]


# C2 voice resolution


def test_a_configured_voice_sends_no_listing_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"), "abc123")

    assert server.requests == []
    drain(tts)

    [post] = server.posts()
    assert post.url.path == "/v1/text-to-speech/abc123/stream"
    assert server.gets("/v2/voices") == []


def test_auto_lists_the_account_once_with_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server = build(monkeypatch, account([voice("v1", "pt-BR")]), "auto")

    [request] = server.requests
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == f"{BASE}/v2/voices"
    assert dict(request.url.params) == {"page_size": "100"}
    assert request.headers["xi-api-key"] == KEY


def test_the_first_pt_br_voice_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    voices = [voice("en1", "en-US"), voice("first", "pt-BR"), voice("second", "pt-BR")]

    assert resolved(monkeypatch, voices) == "first"


@pytest.mark.parametrize(
    "entry",
    [
        voice("x", locale="PT-br"),
        voice("x", language="pt", accent="Brazilian"),
        voice("x", language="PT", accent="BRAZILIAN portuguese"),
        voice("x", language="pt", locale="pt-BR", accent="european"),
    ],
)
def test_pt_br_is_matched_by_locale_or_by_language_and_accent(
    monkeypatch: pytest.MonkeyPatch, entry: dict[str, Any]
) -> None:
    other = voice("miss", "en-US")

    assert resolved(monkeypatch, [other, entry]) == "x"


@pytest.mark.parametrize(
    "entry",
    [
        voice("x", language="pt", accent="european"),
        voice("x", language="pt"),
        voice("x", language="en", accent="brazilian"),
        voice("x", accent="brazilian"),
        voice("x", locale="pt-PT"),
        {"voice_id": "x", "verified_languages": None},
        {"voice_id": "x"},
        {"voice_id": "x", "verified_languages": ["pt-BR", 3, None]},
        {"voice_id": "x", "verified_languages": [{"locale": 5, "language": 5}]},
    ],
)
def test_other_voices_are_not_pt_br(
    monkeypatch: pytest.MonkeyPatch, entry: dict[str, Any]
) -> None:
    reason = unavailable(monkeypatch, shared_voices(account([entry])))

    assert reason.startswith("no pt-BR voice in the ElevenLabs account")


def shared_voices(listing_handler: Handler, shared: Any = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/shared-voices":
            return json_response(shared if shared is not None else {"voices": []})
        return listing_handler(request)

    return handler


def test_a_pt_br_voice_on_page_two_is_found_with_the_page_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("next_page_token") == "T1":
            return listing([voice("late", "pt-BR")])
        return listing([voice("en1", "en-US")], has_more=True, token="T1")

    tts, server = build(monkeypatch, handler, "auto")

    assert tts.voice == "late"
    assert [r.url.params.get("next_page_token") for r in server.requests] == [
        None,
        "T1",
    ]
    assert all(r.url.params["page_size"] == "100" for r in server.requests)


def test_listing_stops_after_ten_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/shared-voices":
            return json_response({"voices": []})
        token = request.url.params.get("next_page_token")
        calls.append(token)
        number = 0 if token is None else int(token)
        return listing([voice("en", "en-US")], has_more=True, token=str(number + 1))

    reason = unavailable(monkeypatch, handler)

    assert calls == [None, *(str(n) for n in range(1, 10))]
    assert reason.startswith("no pt-BR voice")


def test_a_pt_br_voice_on_the_tenth_page_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("next_page_token")
        number = 0 if token is None else int(token)
        if number == 9:
            return listing([voice("tenth", "pt-BR")])
        return listing([voice("en", "en-US")], has_more=True, token=str(number + 1))

    tts, _ = build(monkeypatch, handler, "auto")

    assert tts.voice == "tenth"


@pytest.mark.parametrize("token", [None, ""])
def test_listing_stops_without_has_more_or_a_token(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    server = install(
        monkeypatch,
        shared_voices(
            lambda request: (
                listing([voice("en", "en-US")], has_more=False, token="T")
                if token is None
                else listing([voice("en", "en-US")], has_more=True, token=token)
            )
        ),
    )

    with pytest.raises(ProviderUnavailable):
        ElevenLabsTts("auto", "m")

    assert len(server.gets("/v2/voices")) == 1


def test_no_pt_br_voice_lists_up_to_three_shared_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = {
        "voices": [
            {"name": "A", "voice_id": "id1"},
            {"name": "B", "voice_id": "id2"},
            {"name": "C", "voice_id": "id3"},
            {"name": "D", "voice_id": "id4"},
        ]
    }
    server = install(monkeypatch, shared_voices(account([]), shared))

    with pytest.raises(ProviderUnavailable) as raised:
        ElevenLabsTts("auto", "m")

    assert raised.value.reason == (
        "no pt-BR voice in the ElevenLabs account; "
        "add one from the voice library: A (id1), B (id2), C (id3)"
    )
    [request] = server.gets("/v1/shared-voices")
    assert str(request.url.copy_with(query=None)) == f"{BASE}/v1/shared-voices"
    assert dict(request.url.params) == {
        "language": "pt",
        "locale": "pt-BR",
        "page_size": "3",
    }
    assert request.headers["xi-api-key"] == KEY


_BARE = "no pt-BR voice in the ElevenLabs account; add one from the voice library"


@pytest.mark.parametrize(
    "response",
    [
        json_response({"voices": []}),
        json_response({"voices": [{"name": "A"}, 5, {"voice_id": "i"}]}),
        json_response({"voices": "x"}),
        json_response([1]),
        httpx.Response(200, content=b"not json"),
        httpx.Response(500, content=b"boom"),
    ],
)
def test_an_empty_failed_or_malformed_library_leaves_the_bare_hint(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/shared-voices":
            return response
        return listing([])

    assert unavailable(monkeypatch, handler) == _BARE


def test_a_library_request_error_leaves_the_bare_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/shared-voices":
            raise httpx.ConnectError("down")
        return listing([])

    assert unavailable(monkeypatch, handler) == _BARE


def test_only_complete_library_entries_are_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = {"voices": [{"name": "A"}, {"name": "B", "voice_id": "i2"}, "x"]}

    reason = unavailable(monkeypatch, shared_voices(account([]), shared))

    assert reason == f"{_BARE}: B (i2)"


def test_a_failed_account_listing_is_unavailable_with_the_http_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"detail": {"status": "invalid_api_key", "message": f"bad key {KEY}"}}

    reason = unavailable(monkeypatch, lambda request: json_response(body, 401))

    assert reason == "elevenlabs returned HTTP 401: bad key ***"


def test_a_failed_account_listing_does_not_ask_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = install(monkeypatch, lambda request: httpx.Response(500, content=b"x"))

    with pytest.raises(ProviderUnavailable):
        ElevenLabsTts("auto", "m")

    assert len(server.requests) == 1


def test_a_listing_connection_error_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {KEY}")

    reason = unavailable(monkeypatch, handler)

    assert reason == "elevenlabs request failed: ConnectError"
    assert KEY not in reason


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        json_response([1]),
        json_response({"voices": "x"}),
        json_response({"voices": [{"name": "no id"}]}),
        json_response({"voices": [{"voice_id": 5}]}),
        json_response({"voices": ["x"]}),
        json_response({}),
    ],
)
def test_a_malformed_listing_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    reason = unavailable(monkeypatch, lambda request: response)

    assert reason == "elevenlabs returned an unreadable voice list"


def test_the_listing_client_is_closed_after_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server = build(monkeypatch, account([voice("v", "pt-BR")]), "auto")

    [client] = server.clients
    assert client.is_closed


def test_the_listing_client_is_closed_when_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = install(monkeypatch, lambda request: httpx.Response(500))

    with pytest.raises(ProviderUnavailable):
        ElevenLabsTts("auto", "m")

    assert all(client.is_closed for client in server.clients)


# C3 request and stream


def test_sends_one_post_with_the_exact_url_header_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"), "VOICE_ID", "eleven_x")

    drain(tts, "olá mundo")

    [request] = server.requests
    assert request.method == "POST"
    assert request.url.path == "/v1/text-to-speech/VOICE_ID/stream"
    assert str(request.url) == (
        f"{BASE}/v1/text-to-speech/VOICE_ID/stream?output_format=pcm_24000"
    )
    assert request.headers["xi-api-key"] == KEY
    assert json.loads(request.content) == {"text": "olá mundo", "model_id": "eleven_x"}
    assert tts.name == "elevenlabs"


@pytest.mark.parametrize(
    ("voice_id", "segment"),
    [("a/b?c#d", "a%2Fb%3Fc%23d"), ("../x", "..%2Fx"), ("a b", "a%20b")],
)
def test_a_hostile_voice_id_stays_one_path_segment(
    monkeypatch: pytest.MonkeyPatch, voice_id: str, segment: str
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"), voice_id)

    drain(tts)

    [request] = server.requests
    path, _, query = request.url.raw_path.decode().partition("?")
    assert path == f"/v1/text-to-speech/{segment}/stream"
    assert query == "output_format=pcm_24000"
    assert dict(request.url.params) == {"output_format": "pcm_24000"}


def test_pieces_of_odd_size_yield_only_even_chunks_at_24khz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pieces = (b"\x01\x02\x03", b"\x04", b"\x05\x06\x07\x08")
    tts, _ = build(monkeypatch, streamed(*pieces))

    chunks = drain(tts)

    assert all(len(c.pcm) % 2 == 0 and c.pcm for c in chunks)
    assert {c.sample_rate for c in chunks} == {24000}
    assert b"".join(c.pcm for c in chunks) == b"".join(pieces)


def test_first_chunk_is_yielded_before_the_body_is_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed: list[int] = []

    def body() -> Iterator[bytes]:
        for index in range(3):
            consumed.append(index)
            yield b"\x00\x01"

    tts, _ = build(monkeypatch, lambda request: httpx.Response(200, content=body()))
    stream = tts.synthesize("hello")

    first = next(stream)

    assert first.pcm == b"\x00\x01"
    assert consumed == [0]
    close(stream)


def test_odd_total_length_raises_after_the_aligned_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts, _ = build(monkeypatch, streamed(b"\x01\x02", b"\x03\x04\x05"))
    heard = b""

    with pytest.raises(RuntimeError) as raised:
        for chunk in tts.synthesize("hello"):
            heard += chunk.pcm

    assert heard == b"\x01\x02\x03\x04"
    assert str(raised.value) == "elevenlabs returned audio with 1 odd byte"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_text_yields_nothing_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    tts, server = build(monkeypatch, streamed(b"ab"))

    assert drain(tts, text) == []
    assert server.requests == []
    assert server.clients == []


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
    tts, server = build(monkeypatch, lambda r: httpx.Response(500, content=b"boom"))

    with pytest.raises(RuntimeError):
        drain(tts)

    [client] = server.clients
    assert client.is_closed


# C4 errors


def failure(
    status: int, body: bytes, content_type: str = "application/json"
) -> Handler:
    return lambda request: httpx.Response(
        status, content=body, headers={"content-type": content_type}
    )


def raised_message(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> str:
    tts, _ = build(monkeypatch, handler)
    with pytest.raises(RuntimeError) as raised:
        drain(tts)
    return str(raised.value)


def test_a_401_that_echoes_the_key_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "detail": {"status": "invalid_api_key", "message": f"Invalid API key: {KEY}"}
    }

    message = raised_message(monkeypatch, failure(401, json.dumps(body).encode()))

    assert message == "elevenlabs returned HTTP 401: Invalid API key: ***"
    assert KEY not in message


def test_a_422_list_detail_reports_the_first_msg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"detail": [{"loc": ["body", "text"], "msg": "field required", "type": "x"}]}

    message = raised_message(monkeypatch, failure(422, json.dumps(body).encode()))

    assert message == "elevenlabs returned HTTP 422: field required"


def test_a_422_with_an_empty_detail_falls_back_to_the_body_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = raised_message(monkeypatch, failure(422, b'{"detail": []}'))

    assert message == 'elevenlabs returned HTTP 422: {"detail": []}'


@pytest.mark.parametrize(
    "body",
    [
        b'{"detail": "nope"}',
        b'{"detail": {"status": "x"}}',
        b'{"detail": {"message": 5}}',
        b'{"detail": [{"loc": []}]}',
        b'{"detail": ["x"]}',
        b'{"detail": [{"msg": 5}]}',
        b'{"message": "top"}',
        b"[1]",
    ],
)
def test_a_body_without_a_usable_message_falls_back_to_the_text(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    message = raised_message(monkeypatch, failure(502, body))

    assert message == f"elevenlabs returned HTTP 502: {body.decode()}"


def test_a_message_keeps_only_its_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"detail": {"message": "first\nsecond"}}).encode()

    message = raised_message(monkeypatch, failure(400, body))

    assert message == "elevenlabs returned HTTP 400: first"


def test_a_long_error_body_is_cut_to_200_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = raised_message(monkeypatch, failure(500, b"x" * 10_000, "text/plain"))

    assert message == "elevenlabs returned HTTP 500: " + "x" * 200


def test_only_4096_bytes_of_an_error_body_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed: list[int] = []

    def body() -> Iterator[bytes]:
        for index in range(100):
            consumed.append(index)
            yield b"z" * 1024

    message = raised_message(
        monkeypatch, lambda request: httpx.Response(500, content=body())
    )

    assert message == "elevenlabs returned HTTP 500: " + "z" * 200
    assert len(consumed) <= 5


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, b"", "elevenlabs returned HTTP 500: Internal Server Error"),
        (503, b"  \n ", "elevenlabs returned HTTP 503: Service Unavailable"),
        (
            401,
            b'{"detail": {"message": ""}}',
            "elevenlabs returned HTTP 401: Unauthorized",
        ),
        (599, b"", "elevenlabs returned HTTP 599"),
    ],
)
def test_an_error_without_a_usable_message_falls_back_to_the_reason(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes, expected: str
) -> None:
    assert raised_message(monkeypatch, failure(status, body, "text/plain")) == expected


def test_a_connection_error_text_does_not_contain_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    tts, _ = build(monkeypatch, handler)

    with pytest.raises(httpx.ConnectError) as raised:
        drain(tts)

    assert KEY not in str(raised.value)


def test_a_failed_library_reply_with_voices_in_its_body_is_not_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/shared-voices":
            return json_response({"voices": [{"name": "A", "voice_id": "i"}]}, 500)
        return listing([])

    assert unavailable(monkeypatch, handler) == _BARE


def test_synthesis_hands_the_transport_to_the_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.BaseTransport | None] = []
    inner = httpx.MockTransport(lambda request: httpx.Response(200, content=b"ab"))

    def spy(transport: httpx.BaseTransport | None = None) -> httpx.Client:
        seen.append(transport)
        return httpx.Client(transport=inner)

    monkeypatch.setattr(models, "make_client", spy)
    transport = httpx.MockTransport(lambda request: httpx.Response(200))

    drain(ElevenLabsTts("v", "m", transport))

    assert seen == [transport]


def test_the_registry_defaults_to_auto_and_the_first_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, account([voice("found", "pt-BR")]))

    tts = create_tts("elevenlabs", {})

    assert isinstance(tts, ElevenLabsTts)
    assert (tts.voice, tts.model) == ("found", "eleven_flash_v2_5")


def test_the_registry_builds_the_adapter_from_its_options() -> None:
    tts = create_tts("elevenlabs", {"voice": "v9", "model": "eleven_x"})

    assert isinstance(tts, ElevenLabsTts)
    assert (tts.voice, tts.model) == ("v9", "eleven_x")
