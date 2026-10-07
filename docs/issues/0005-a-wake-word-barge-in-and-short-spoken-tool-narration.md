---
type: Issue
title: A wake word, barge-in and short spoken tool narration
description: "Slice 5: openWakeWord on Jarvis, the reply cut when the owner speaks, and one short spoken line per tool call."
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T19:48:19Z
---

## 0005. A wake word, barge-in and short spoken tool narration

Makes the open channel comfortable to live with: it waits for a wake word, stops talking when the owner talks, and says briefly what the model is doing. Builds on issue 0004 and the `WakeWord` port of [ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md).

### Scope

- The `WakeWord` port with an openWakeWord adapter on "Jarvis".
- Barge-in: speech while the sidecar is speaking cuts its audio, emits an event, and the mod aborts the turn.
- Tool narration: a `tool.call` hook sends one short line per call to `speak`.

### Acceptance

- With the wake word on, speech without "Jarvis" first is not submitted.
- Speaking over a reply stops the audio within a bound measured and recorded here, and the turn is aborted.
- Each tool call is narrated in one short line, and narration never queues behind a long reply.
