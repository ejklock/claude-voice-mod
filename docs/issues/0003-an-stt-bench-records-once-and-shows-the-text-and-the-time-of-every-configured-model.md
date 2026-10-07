---
type: Issue
title: An STT bench records once and shows the text and the time of every configured model
description: "Slice 3: the SpeechToText port, the mlx-whisper, OpenAI and Deepgram adapters, and a bench over one recording."
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T19:48:19Z
---

## 0003. An STT bench records once and shows the text and the time of every configured model

The owner picks the default transcription model by its accuracy and speed on their own voice, so the bench records one utterance and runs every model over the same audio. Implements the transcription side of [ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md).

### Scope

- The `SpeechToText` port and microphone capture in the sidecar.
- Local adapters: mlx-whisper with `large-v3-turbo` and `small`.
- External adapters: OpenAI (key present, runs in the bench) and Deepgram (no key yet; built and tested with a stub server, skipped in the bench).
- `voice bench stt`: record once, then print each model's text and time.
- Out of scope: the daemon, voice activity detection for a live channel, and the mod.

### Acceptance

- `voice bench stt` records one utterance and prints, per available model, the transcript and the transcription time.
- The same recording feeds every model, and it can be replayed from a file to repeat the bench.
- A model whose key or weights are missing is listed as skipped with the reason.
