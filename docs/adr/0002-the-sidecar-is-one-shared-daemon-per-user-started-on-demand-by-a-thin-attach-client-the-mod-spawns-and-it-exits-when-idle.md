---
type: ADR
title: The sidecar is one shared daemon per user, started on demand by a thin attach client the mod spawns, and it exits when idle
description: The mod spawns voice-sidecar attach, which connects to the user's daemon over its Unix socket or starts it, and relays its events as JSON lines; the daemon keeps the models warm across sessions, owns the microphone alone and exits after an idle timeout.
owner: Evaldo Klock
status: Proposed
timestamp: 2026-10-07T20:46:18Z
---

# 0002. The sidecar is one shared daemon per user, started on demand by a thin attach client the mod spawns, and it exits when idle

## Context

[ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md) has the mod start the sidecar with `$.process.spawn` at `session.start`, so the sidecar lives and dies with one session. The owner asked for high performance and responsiveness. Under that lifecycle every session pays the load of the speech models again (seconds, not yet measured), and two sessions open at once start two sidecars that fight over one microphone.

The mod's channel constraints stay as ADR 0001 found them: events reach the mod only through a spawned child's stdout, and commands go out through `$.http.fetch` over a Unix socket.

## Decision

We will run one sidecar daemon per user, reached at a fixed Unix socket under the user's runtime directory. The mod spawns `voice-sidecar attach` at `session.start`. `attach` connects to the daemon's socket, or starts the daemon detached and waits until it is ready, then relays the daemon's events to its own stdout as JSON lines, so the mod's side of ADR 0001's channel is unchanged. Commands still go from the mod to the daemon's socket. The daemon keeps the models loaded, owns the microphone alone, serves one attached session at a time as the active listener, and exits after an idle timeout with no client attached. `attach` and the daemon exchange their protocol version on connect; a mismatch restarts the daemon once it is idle.

The owner chose this on 2026-10-07, between the options below.

Rejected alternatives:

- **One sidecar per session (ADR 0001 as written).** Simplest, nothing left running, but every session pays the model load, and parallel sessions contend for the microphone.
- **A launchd agent started at login.** Lowest latency, but a heavier install, and 1–2 GB of models held in memory all day whether or not voice is used.

## Consequences

**Easier / gained:**
- Models stay warm across sessions; only the first session after an idle exit pays the load.
- One process owns the microphone, so sessions cannot fight over it.
- The mod is unchanged from ADR 0001: it still reads JSON lines from a spawned child and sends commands to a socket.

**Harder / accepted trade-offs:**
- The daemon has a lifecycle of its own: a stale socket from a crash, two `attach` racing to start it, an old daemon after an upgrade, and the idle timeout.
- Which attached session is the active listener needs a rule and a visible state in the band.
- The daemon outlives the session that started it, for up to the idle timeout.

**Follow-ups:**
- [Issue 0004](/issues/0004-the-mod-opens-the-channel-at-session-start-and-holds-a-continuous-spoken-conversation-with-a-status-band.md) builds `attach`, the daemon lifecycle and the latency events.

## Verification

**Implementation impact:** the sidecar's daemon and `attach` entry points, the socket location, and the mod's `session.start` hook.

**Verification criteria:**
- Two `attach` processes started at the same moment leave exactly one daemon running.
- A socket file left by a killed daemon does not block the next `attach`, which starts a fresh daemon.
- With no client attached, the daemon exits after the idle timeout and frees the microphone.
- A second session's `attach` reuses the warm daemon: its time to ready is measured and recorded in issue 0004, and is below the cold start.
