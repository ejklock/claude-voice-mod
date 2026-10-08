---
type: Issue
title: A cloning TTS adapter speaks in a voice taken from a reference audio file the owner configures, in any language the engine supports
description: Research the local voice-cloning engines for pt-BR on Apple silicon, then add a clone adapter whose reference audio comes only from the owner's local configuration.
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T20:46:18Z
---

## 0006. A cloning TTS adapter speaks in a voice taken from a reference audio file the owner configures, in any language the engine supports

The owner wants a voice like TARS from Interstellar, multilingual, as fan projects (OpenTARS, the GPTARS family) built with local voice-cloning engines. This adds a `clone` adapter behind the `TextToSpeech` port of [issue 0002](/issues/0002-a-tts-bench-speaks-one-pt-br-sentence-in-every-configured-voice-so-the-owner-can-compare-them.md): it speaks in the voice of a reference audio file and, where the engine allows, in another language than the reference.

### Scope

- A research note comparing the local cloning engines named by those projects (Chatterbox and Chatterbox Multilingual, XTTS v2, F5-TTS, Qwen3-TTS on MLX): pt-BR support and quality, cross-lingual cloning, speed and memory on Apple silicon, streaming, Python range, and licence.
- A `clone` adapter for the engine the owner picks from that note, as an optional extra, whose reference audio path comes only from the owner's configuration.
- One clone row in the TTS bench when a reference is configured.

**Kept out on purpose:** this public repository never ships, links to or downloads reference audio of a real person, or a voice model cloned from one. What the owner configures locally is the owner's choice and responsibility.

### Acceptance

- The research note is recorded, and the owner picks the engine from it.
- With a reference file configured, `voice-sidecar bench tts` speaks the sentence in the cloned voice, in pt-BR and in English.
- With no reference configured, the clone adapter is skipped with a line naming the missing setting.
- The repository holds no reference audio file and no cloned voice model.
