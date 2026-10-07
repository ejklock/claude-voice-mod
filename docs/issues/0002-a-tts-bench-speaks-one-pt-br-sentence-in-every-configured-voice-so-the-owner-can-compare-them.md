---
type: Issue
title: A TTS bench speaks one pt-BR sentence in every configured voice so the owner can compare them
description: "Slice 2: the TextToSpeech port, the say, Kokoro, Piper, OpenAI and ElevenLabs adapters, and a bench that plays and times each."
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T19:48:19Z
---

## 0002. A TTS bench speaks one pt-BR sentence in every configured voice so the owner can compare them

The owner picks the default voice by ear, so the first port built is `TextToSpeech`, with a bench that plays the same Brazilian Portuguese sentence in every voice and times it. Implements the speech side of [ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md).

### Scope

- The `TextToSpeech` port and the local adapters `say` (Luciana), Kokoro and Piper.
- The external adapters OpenAI and ElevenLabs, each reading its key from the environment (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`); the owner has both keys, so both run in the bench.
- `voice bench tts`: one sentence, each adapter in turn, printing the adapter, the time to the first audio and the total time; an adapter whose key or model is missing is listed as skipped with the reason.
- Out of scope: the microphone, the daemon and the mod.

### Acceptance

- `voice bench tts` plays the sentence in every available voice and prints one row per adapter with its timings.
- An external adapter with no key is skipped with a line naming the missing variable, and no request is sent.
- With no configuration, the port resolves to a local adapter.
