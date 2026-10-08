---
type: Issue
title: The mod opens the channel at session start and holds a continuous spoken conversation with a status band
description: "Slice 4: the sidecar daemon, the mod client, transcripts submitted as prompts, replies spoken, and the AbovePrompt band."
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T19:48:19Z
---

## 0004. The mod opens the channel at session start and holds a continuous spoken conversation with a status band

Connects the sidecar to Claude Code: the conversation itself. Runs [ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md) end to end and decides whether it moves to Accepted.

### Scope

- The sidecar daemon, one per user per [ADR 0002](/adr/0002-the-sidecar-is-one-shared-daemon-per-user-started-on-demand-by-a-thin-attach-client-the-mod-spawns-and-it-exits-when-idle.md): `voice-sidecar attach` connects to it or starts it, relays its events as JSON lines, and the daemon exits when idle. It listens continuously, detects the end of an utterance by voice activity, cancels the echo of its own speech, and serves `speak`, `stop` and `mute` on a Unix socket.
- The latency budget of Amendment 1 to the constitution: the daemon emits each stage's time, the reply is spoken sentence by sentence from `turn.step`, and the band shows the last turn's time to first audio.
- The mod: `hooks/register.ts` starts the sidecar at `session.start`, `hooks/channel.ts` parses events and sends commands, `hooks/band.tsx` draws the band.
- Each transcript is submitted with `$.prompt.submit({ text, asUser: true })`; the reply from `turn.step` and `turn.complete` is spoken.
- The band above the prompt: ● listening, ◐ thinking, ▶ speaking, the microphone level, the active providers and the last transcript.
- The Node toolchain, `install.sh` and `claude plugin test` in CI; a demo GIF in the README.
- Out of scope: wake word, barge-in and tool narration (issue 0005).

### Acceptance

- In a session started with the plugin, a spoken question is submitted as the prompt and the reply is heard, with no key pressed.
- The band shows the state that matches the channel at each step.
- A malformed event line is rejected by the mod's schema and the channel keeps running.
- Ending the session stops the sidecar and frees the microphone.
