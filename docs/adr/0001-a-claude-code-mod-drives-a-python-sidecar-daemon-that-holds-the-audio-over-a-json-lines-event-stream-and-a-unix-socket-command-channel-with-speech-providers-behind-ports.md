---
type: ADR
title: A Claude Code mod drives a Python sidecar daemon that holds the audio, over a JSON-lines event stream and a Unix-socket command channel, with speech providers behind ports
description: "The mod is a thin client of a uv-managed Python sidecar: events come up its stdout as JSON lines, commands go down a Unix socket, and STT, TTS and wake word sit behind ports with local adapters by default."
owner: Evaldo Klock
status: Accepted
timestamp: 2026-10-07T19:48:19Z
---

# 0001. A Claude Code mod drives a Python sidecar daemon that holds the audio, over a JSON-lines event stream and a Unix-socket command channel, with speech providers behind ports

## Context

The owner wants a voice mode for Claude Code like the one in the Codex CLI: a channel that stays open, so speaking is the prompt and the reply is heard, with no key to press per turn.

A Claude Code mod (Claude Code 2.1.292) runs its hooks module in an environment with no Node and no DOM, and it has no microphone API. What it does have, read from this build's type declarations: `$.process.spawn` streams a child's stdout for as long as the child runs; `$.http.fetch` reaches a Unix socket through `socketPath`, but returns the body only as text; `$.prompt.submit` sends text as the user's prompt; `turn.step` and `turn.complete` carry the reply; `$.audio.speak` uses macOS `say` and queues, with no way to cut it; `$.audio.play` takes an asset, a URL or base64 bytes and can be aborted.

So capture, speech-to-text and wake-word detection cannot run in the mod. The mature local speech stack on Apple silicon (mlx-whisper, Kokoro, Piper, openWakeWord) is Python. The owner also wants to compare providers, local and external, without rewiring the mod for each.

## Decision

We will build the mod as a thin client of a Python sidecar daemon managed by `uv`. The mod starts the sidecar with `$.process.spawn` at `session.start`. *(The sidecar's lifecycle is refined by [ADR 0002](/adr/0002-the-sidecar-is-one-shared-daemon-per-user-started-on-demand-by-a-thin-attach-client-the-mod-spawns-and-it-exits-when-idle.md): the spawned child is a thin `attach` client of one shared daemon.)* The sidecar owns the microphone and the speaker and sends events to the mod as one JSON object per line on its stdout (`transcript`, `speech_started`, `wake`, and the band's state and level). The mod sends commands to the sidecar with `$.http.fetch` over a Unix socket the sidecar listens on (`speak`, `stop`, `mute`). A transcript becomes `$.prompt.submit({ text, asUser: true })`. The reply text, from `turn.step` and `turn.complete`, goes back down as `speak`. On barge-in the sidecar cuts its own audio and emits an event, and the mod aborts the turn.

Inside the sidecar, speech-to-text, text-to-speech and wake-word detection are ports (`SpeechToText`, `TextToSpeech`, `WakeWord`), and each provider is an adapter chosen by configuration. With no configuration every port runs a local adapter: `say` (voice Luciana), Kokoro or Piper for speech; mlx-whisper for transcription; openWakeWord for the wake word. External adapters (OpenAI and ElevenLabs for speech, OpenAI and Deepgram for transcription) run only when configured, with the key read from the environment.

The owner chose this direction on 2026-10-07. It stays Proposed until issue 0004 runs the channel end to end.

Rejected alternatives:

- **Everything in the mod.** The mod has no microphone API and no Node, so it cannot capture audio or run a model. `$.audio.speak` cannot be interrupted, which rules out barge-in.
- **The sidecar as a one-shot command per turn** (record, transcribe, exit). Each turn would pay model load time, and the channel could not stay open to hear a wake word or a barge-in.
- **Commands through the sidecar's stdin.** `$.process.spawn` writes its `input` text once at start and then closes standard input, so commands sent later need a second channel. A Unix socket keeps it local, with no port to collide or to expose.
- **Audio produced by external APIs fetched by the mod and played with `$.audio.play`.** `$.http.fetch` returns the body as text, so binary audio does not come back clean. External adapters run in the sidecar instead.
- **A Node or Swift sidecar.** Node lacks the local speech models; Swift has Apple's speech framework but not Whisper-class pt-BR accuracy or the other models. Either way the comparison the owner wants would be poorer.
- **A Rust sidecar.** It would start in milliseconds, use less memory, keep the audio loop free of interpreter pauses and ship as one binary. But the models already run in native code (Metal, ONNX Runtime, PyTorch), so the language of the glue costs milliseconds on a path of seconds; and Rust loses mlx-whisper and the original Kokoro, narrowing the comparison. The owner chose on 2026-10-07 to keep Python and revisit Rust only if the benches of issues 0002 and 0003 show the sidecar's own overhead in the latency. The protocol is language-neutral, so a Rust daemon could replace this one without changing the mod.
- **One fixed provider per port, no ports.** Simpler, but every comparison and every later switch would change the daemon's code.

## Consequences

**Easier / gained:**
- The channel stays open: models load once, and the sidecar can hear a wake word and a barge-in while it speaks.
- A provider is swapped by configuration, and the benches run every adapter through the same port.
- The mod stays small and holds no audio code; the sidecar can be tested without Claude Code.
- By default nothing leaves the machine.

**Harder / accepted trade-offs:**
- The project ships two languages and two toolchains (TypeScript for the mod, Python with `uv` for the sidecar), and installing the mod also installs the sidecar's environment and its models.
- The mods API is early access and may change without notice.
- Two processes must agree on a protocol; both sides parse every message with a schema, and the protocol changes in one commit on both sides.
- The sidecar holds the microphone while the session runs; mute is a command, and the band shows the state.

**Follow-ups:**
- [Issue 0001](/issues/0001-the-repository-skeleton-the-sidecar-toolchain-and-the-ci-gates-are-green-with-no-voice-behavior-yet.md): the skeleton and the gates.
- [Issue 0002](/issues/0002-a-tts-bench-speaks-one-pt-br-sentence-in-every-configured-voice-so-the-owner-can-compare-them.md) and [issue 0003](/issues/0003-an-stt-bench-records-once-and-shows-the-text-and-the-time-of-every-configured-model.md): the ports, their adapters and the benches.
- [Issue 0004](/issues/0004-the-mod-opens-the-channel-at-session-start-and-holds-a-continuous-spoken-conversation-with-a-status-band.md): the channel end to end, which moves this record to Accepted or supersedes it.

## Verification

**Implementation impact:** the mod's hooks module (`hooks/`), the sidecar package (`sidecar/`, with `ports/`, `adapters/local/`, `adapters/external/` and `bench/`), and the protocol both sides parse.

**Verification criteria:**
- No source file under `hooks/` captures or plays audio: it never calls `$.audio.speak` or `$.audio.play`.
- With no configuration, the sidecar selects a local adapter for every port, and no adapter under `adapters/external/` is imported.
- An external adapter with no key in the environment fails with a plain error naming the variable, before any request.
- A malformed event or command line is rejected by the receiving side's schema and does not crash the channel.

# References

[1] [Claude Code mods API — the type declarations of the installed build (2.1.292)](https://claude.com/claude-code)
[2] [Codex CLI](https://github.com/openai/codex)
