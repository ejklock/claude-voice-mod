import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version

from voice_sidecar import models
from voice_sidecar.audio.speaker import SoundDeviceSpeaker, Speaker
from voice_sidecar.bench.tts import BenchVoice, render_table, run_tts_bench
from voice_sidecar.providers import TTS_PROVIDERS, create_tts

DEFAULT_SENTENCE = (
    "Olá! Eu sou o Claude. Posso ler o seu código, rodar os testes e explicar "
    "o que encontrei."
)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="voice-sidecar")
    parser.add_argument("--version", action="version", version=version("voice-sidecar"))
    commands = parser.add_subparsers(dest="command", required=True)
    bench = commands.add_parser("bench", help="compare providers by ear and by clock")
    targets = bench.add_subparsers(dest="target", required=True)
    tts = targets.add_parser("tts", help="speak one sentence in every voice")
    tts.add_argument("--text", default=DEFAULT_SENTENCE, help="the sentence to speak")
    tts.add_argument(
        "--voice",
        action="append",
        type=_voice_spec,
        help="provider:voice[@model] to bench; repeatable; "
        "default is every known voice",
    )
    tts.add_argument(
        "--no-play", action="store_true", help="time the voices without playing them"
    )
    tts.set_defaults(handler=_bench_tts_command, parser=tts)
    stored = commands.add_parser("models", help="manage the speech model files")
    actions = stored.add_subparsers(dest="action", required=True)
    fetch = actions.add_parser("fetch", help="download an engine's pinned model files")
    fetch.add_argument(
        "engine",
        nargs="+",
        choices=models.engines(),
        help="the engine whose files to download",
    )
    fetch.set_defaults(handler=_models_fetch_command)
    if not args:
        parser.error("a flag is required")
    parsed = parser.parse_args(args)
    parsed.handler(parsed)


def _bench_tts_command(parsed: argparse.Namespace) -> None:
    if not parsed.text.strip():
        parsed.parser.error("the text must not be empty")
    _bench_tts(parsed.text, parsed.voice, play=not parsed.no_play)


def _models_fetch_command(parsed: argparse.Namespace) -> None:
    failed = False
    terminal = sys.stderr.isatty()

    def show_progress(name: str, done: int, total: int) -> None:
        percent = done * 100 // total
        sys.stderr.write(
            f"\r{engine}  {name}  {percent}%  {done / 1e6:.1f} of {total / 1e6:.1f} MB"
        )
        sys.stderr.flush()

    def show_result(result: models.FetchResult) -> None:
        nonlocal failed
        if terminal:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()
        print(_fetch_line(result), flush=True)
        failed |= result.outcome == "failed"

    with models.make_client() as client:
        for engine in parsed.engine:
            models.fetch_engine(
                engine,
                client,
                models.cache_root(),
                progress=show_progress if terminal else None,
                on_result=show_result,
            )
    if failed:
        raise SystemExit(1)


def _fetch_line(result: models.FetchResult) -> str:
    line = f"{result.engine}  {result.name}  {result.outcome}"
    return line if result.reason is None else f"{line}  {result.reason}"


@dataclass(frozen=True)
class VoiceSpec:
    provider: str
    voice: str
    model: str | None

    @property
    def label(self) -> str:
        base = f"{self.provider}:{self.voice}"
        return base if self.model is None else f"{base}@{self.model}"

    @property
    def options(self) -> dict[str, str]:
        options = {"voice": self.voice}
        if self.model is not None:
            options["model"] = self.model
        return options


def _voice_spec(spec: str) -> VoiceSpec:
    name, separator, rest = spec.partition(":")
    provider = TTS_PROVIDERS.get(name)
    if provider is None or not separator or not rest:
        known = ", ".join(sorted(TTS_PROVIDERS))
        raise argparse.ArgumentTypeError(
            f"invalid voice {spec!r}: expected provider:voice[@model] with a "
            f"provider among {known}"
        )
    voice, at, model = rest.rpartition("@")
    if not at:
        voice, model = rest, ""
    problem = None
    if not voice:
        problem = "the voice must not be empty"
    elif at and not model:
        problem = "the model must not be empty"
    elif at and not provider.default_models:
        problem = f"provider {name!r} takes no model"
    if problem is not None:
        raise argparse.ArgumentTypeError(f"invalid voice {spec!r}: {problem}")
    chosen: str | None = None
    if model:
        chosen = model
    elif provider.default_models:
        chosen = provider.default_models[0]
    return VoiceSpec(name, voice, chosen)


def _default_specs() -> list[VoiceSpec]:
    return [
        VoiceSpec(name, voice, model)
        for name, provider in TTS_PROVIDERS.items()
        for voice in provider.default_voices
        for model in provider.default_models or (None,)
    ]


def _bench_tts(text: str, specs: list[VoiceSpec] | None, play: bool) -> None:
    if specs is None:
        specs = _default_specs()
    voices = [_bench_voice(spec) for spec in specs]
    speaker: Speaker | None = SoundDeviceSpeaker() if play else None
    try:
        rows = run_tts_bench(voices, text, speaker, time.perf_counter)
    finally:
        if speaker is not None:
            speaker.close()
    print(render_table(rows))
    if not any(row.status == "ok" for row in rows):
        print("voice-sidecar: no voice produced audio", file=sys.stderr)
        raise SystemExit(1)


def _bench_voice(spec: VoiceSpec) -> BenchVoice:
    return BenchVoice(spec.label, lambda: create_tts(spec.provider, spec.options))
