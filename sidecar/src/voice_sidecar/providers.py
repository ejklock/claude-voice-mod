from collections.abc import Callable, Mapping
from dataclasses import dataclass

from voice_sidecar.ports.errors import ProviderUnavailable
from voice_sidecar.ports.tts import TextToSpeech

DEFAULT_TTS_PROVIDER = "say"
DEFAULT_TTS_VOICE = "Luciana"
KOKORO_VOICES = ("pf_dora", "pm_alex")
PIPER_VOICES = ("faber", "cadu", "jeff")

TtsFactory = Callable[[Mapping[str, str]], TextToSpeech]


@dataclass(frozen=True)
class TtsProvider:
    factory: TtsFactory
    default_voices: tuple[str, ...]
    default_models: tuple[str, ...] = ()


def _say(options: Mapping[str, str]) -> TextToSpeech:
    from voice_sidecar.adapters.local.say import SayTts

    return SayTts(options.get("voice", DEFAULT_TTS_VOICE))


def _kokoro(options: Mapping[str, str]) -> TextToSpeech:
    from voice_sidecar.adapters.local.kokoro import KokoroTts

    return KokoroTts(options.get("voice", KOKORO_VOICES[0]))


def _piper(options: Mapping[str, str]) -> TextToSpeech:
    from voice_sidecar.adapters.local.piper import PiperTts

    return PiperTts(options.get("voice", PIPER_VOICES[0]))


TTS_PROVIDERS: dict[str, TtsProvider] = {
    "say": TtsProvider(factory=_say, default_voices=(DEFAULT_TTS_VOICE,)),
    "kokoro": TtsProvider(factory=_kokoro, default_voices=KOKORO_VOICES),
    "piper": TtsProvider(factory=_piper, default_voices=PIPER_VOICES),
}


def create_tts(provider: str, options: Mapping[str, str]) -> TextToSpeech:
    """Build the named adapter; its module is imported only here."""
    known = TTS_PROVIDERS.get(provider)
    if known is None:
        raise ProviderUnavailable(f"unknown provider {provider!r}")
    return known.factory(options)
