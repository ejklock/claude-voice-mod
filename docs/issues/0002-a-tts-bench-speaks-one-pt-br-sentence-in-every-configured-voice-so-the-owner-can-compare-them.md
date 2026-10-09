---
type: Issue
title: A TTS bench speaks one pt-BR sentence in every configured voice so the owner can compare them
description: "Slice 2: the TextToSpeech port, the say, Kokoro, Piper, OpenAI and ElevenLabs adapters, and a bench that plays and times each."
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T19:48:19Z
---

## 0002. A TTS bench speaks one pt-BR sentence in every configured voice so the owner can compare them

The owner picks the default voice by ear, so the first port built is `TextToSpeech`, with a bench that plays the same Brazilian Portuguese sentence in every voice and times it. Implements the speech side of [ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md); the evidence is [research 0001](/research/0001-tts-providers-for-brazilian-portuguese-on-macos-apple-silicon-in-october-2026.md).

### Scope

- The `TextToSpeech` port: `synthesize(text)` yields `AudioChunk(pcm, sample_rate)`, mono signed 16-bit little-endian PCM; a provider that cannot run (missing key, extra or model file) raises `ProviderUnavailable` with the reason before any work.
- Local adapters: `say` (Luciana), Kokoro (`kokoro-onnx`, voices `pf_dora` and `pm_alex`) and Piper (`pt_BR-faber-medium`, `pt_BR-cadu-medium`, `pt_BR-jeff-medium`).
- External adapters: OpenAI (`gpt-4o-mini-tts`, voice `marin`, `pcm`) and ElevenLabs (`eleven_flash_v2_5` and `eleven_multilingual_v2`, `pcm_24000`), each reading its key from `OPENAI_API_KEY` or `ELEVENLABS_API_KEY`.
- A configuration file, parsed by a schema, that picks the provider per port; absent, the port runs `say`.
- Playback through `sounddevice`.
- `voice-sidecar bench tts`: one sentence, each voice in turn, printing per row the voice, the time to first audio, the total synthesis time, the audio length, and the real-time factor; a voice that cannot run is listed as skipped with its reason.
- Out of scope: the microphone, the daemon, the mod, ElevenLabs v4 models, and the OpenAI realtime replacement.

### Decision

Choices the owner made on 2026-10-07:

- **OpenAI on `/audio/speech` now**, although its models shut down on 2027-01-06; the move to the realtime replacement is its own issue. Not taken: a realtime WebSocket adapter now, or no OpenAI TTS.
- **`kokoro-onnx`**, not the PyTorch `kokoro` package, which needs Python <3.13 and pulls torch, transformers and spaCy.
- **Kokoro and Piper are optional extras** (`uv sync --extra kokoro --extra piper`), so a default install carries no GPL code; `say` is the local default. Not taken: plain dependencies, or dropping Piper.
- **The ElevenLabs voice is found through the API**: a configured `voice_id` wins; otherwise the adapter takes the first pt-BR voice in the account; with none, it is skipped and the bench lists shared pt-BR voices to add.
- **Model ids have a default in the provider registry, and the configuration file overrides it per provider** (`gpt-4o-mini-tts`; `eleven_flash_v2_5` and `eleven_multilingual_v2`), so the bench runs with no configuration and the OpenAI shutdown is a configuration change. Not taken: model ids only in configuration, with the rows skipped until one is set.
- **A bench voice is named `provider:voice@model`**; without `@model` the provider's default model is used, so the existing names keep working, and `elevenlabs:auto` means the account's first pt-BR voice. Not taken: one provider entry per model.

Cheap choices made here:

- External adapters call the HTTP APIs with `httpx`, not the vendor SDKs: one small dependency, explicit streaming, and tests with `httpx.MockTransport`.
- Configuration is TOML at `$XDG_CONFIG_HOME/claude-voice/config.toml` (default `~/.config/claude-voice/`), parsed with `pydantic`, which the mod–sidecar protocol needs too.
- Model files live under `$XDG_CACHE_HOME/claude-voice/models` (default `~/.cache/claude-voice/models`), fetched by `voice-sidecar models fetch <provider>` and checked by SHA-256.
- Kokoro uses the fp32 model, so the bench compares the best quality each engine offers.
- The two external adapters share one HTTP helper: PCM re-cut on int16 boundaries, and one error line, `PROVIDER returned HTTP STATUS: MESSAGE`. The message keeps only the first line, at most 200 characters, read from at most 4096 bytes of the body, with the key replaced by `***`. A blank message falls back to the HTTP reason phrase.
- ElevenLabs resolves `auto` when the adapter is built, so the lookup never counts in the bench timings. A pt-BR voice has a verified language with locale `pt-BR`, or language `pt` with a Brazilian accent. The lookup reads at most 10 pages of the account's voices. With no match, the skip reason names up to 3 shared pt-BR library voices.
- Tests never reach the network: an autouse fixture clears both keys, and any client built without `httpx.MockTransport` fails fast. The fixture also keeps mutmut's forked runs off the macOS proxy lookup, which aborts them.

### Acceptance

- `voice-sidecar bench tts` plays the sentence in every available voice and prints one row per voice with its timings.
- An external adapter with no key is skipped with a line naming the missing variable, and no request is sent.
- With no configuration file, the port resolves to `say`.
- A malformed configuration file fails with a message naming the field, never with a traceback.

### Plan

1. The port, configuration, `say`, playback and the bench, end to end with one voice.
2. Kokoro and Piper as extras, with `models fetch`.
3. OpenAI and ElevenLabs over `httpx`.
