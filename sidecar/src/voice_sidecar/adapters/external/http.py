from collections.abc import Callable, Iterator

import httpx

from voice_sidecar.ports.tts import AudioChunk

SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
ERROR_BODY_BYTES = 4096
ERROR_MESSAGE_CHARS = 200


def aligned(pieces: Iterator[bytes], provider: str) -> Iterator[AudioChunk]:
    """Re-cut the byte stream on sample boundaries, carrying a split sample over."""
    carry = b""
    for piece in pieces:
        data = carry + piece
        cut = len(data) - len(data) % SAMPLE_WIDTH
        carry = data[cut:]
        if cut:
            yield AudioChunk(pcm=data[:cut], sample_rate=SAMPLE_RATE)
    if carry:
        raise RuntimeError(f"{provider} returned audio with {len(carry)} odd byte")


def failure(
    provider: str,
    key: str,
    response: httpx.Response,
    pick_message: Callable[[str], str],
) -> str:
    """One safe line for a non-2xx response: no key, bounded, never a traceback."""
    message = pick_message(_error_text(response)).replace(key, "***")
    first_line = (message.splitlines() or [""])[0]
    detail = first_line[:ERROR_MESSAGE_CHARS] if first_line.strip() else ""
    detail = detail or response.reason_phrase
    head = f"{provider} returned HTTP {response.status_code}"
    return f"{head}: {detail}" if detail else head


def _error_text(response: httpx.Response) -> str:
    body = b""
    for piece in response.iter_bytes():
        body += piece
        if len(body) >= ERROR_BODY_BYTES:
            break
    return body[:ERROR_BODY_BYTES].decode("utf-8", errors="replace")
