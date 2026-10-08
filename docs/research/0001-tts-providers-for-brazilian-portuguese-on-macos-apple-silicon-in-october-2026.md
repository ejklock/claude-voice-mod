---
type: Research
title: TTS providers for Brazilian Portuguese on macOS Apple silicon in October 2026
description: "say, Kokoro, Piper, OpenAI and ElevenLabs for pt-BR: versions, Python ranges, streaming formats, licenses and the OpenAI TTS deprecation, checked 2026-10-07."
status: Draft
timestamp: 2026-10-07T20:31:02Z
---

# 0001. TTS providers for Brazilian Portuguese on macOS Apple silicon in October 2026

## Question

Which text-to-speech providers can speak Brazilian Portuguese from a Python 3.12 sidecar on macOS Apple silicon, in what audio format and with what streaming, and what does each cost in install weight, licence and lifetime? It feeds the `TextToSpeech` port of [issue 0002](/issues/0002-a-tts-bench-speaks-one-pt-br-sentence-in-every-configured-voice-so-the-owner-can-compare-them.md).

## Method

On 2026-10-07: PyPI pages, package source and READMEs, provider API docs and changelogs, read by a research agent; `say` was run on this machine (macOS 27.0.1). The OpenAI deprecation and the `kokoro-onnx` version and Python range were re-read by the session. Model quality in pt-BR was not measured; that is the bench's job.

## Findings

| Finding | Evidence | Confidence |
|---|---|---|
| `say -v Luciana -o out.wav --data-format=LEI16@24000` writes mono 24 kHz int16 WAV; `say` cannot stream to stdout or a pipe (error -54, or 0 bytes), so first audio equals total synthesis time | run on this machine; `man say` | high |
| `say` writes no audio inside the Claude Code sandbox; the bench runs outside it | run on this machine | high |
| `kokoro-onnx` 0.6.1 (2026-08-19), Python >=3.10,<3.14, MIT wrapper, Apache-2.0 model; pt-BR via `lang="pt-br"`, voices `pf_dora`, `pm_alex`, `pm_santa`; 24 kHz float32; model files from a GitHub release (int8 114 MB, fp16 164 MB, fp32 326 MB, voices 28 MB) | [2], [3], [4] | high |
| `kokoro` (PyTorch) 0.9.4 requires Python <3.13 and pulls torch, transformers and spaCy | [5] | high |
| Kokoro's phonemizer and espeak-ng are GPL-3.0+; espeak-ng ships inside `espeakng-loader`, no Homebrew step | [3], [6] | medium |
| `piper-tts` 1.8.0 (2026-09-04), GPL-3.0+, abi3 arm64 wheel, embeds espeak-ng; pt_BR voices `faber`, `cadu`, `jeff` (medium, 22050 Hz, CC0) and `edresson` (low, 16 kHz, CC BY 4.0); `PiperVoice.synthesize` yields one int16 chunk per sentence | [7], [8] | high |
| OpenAI deprecated `tts-1`, `tts-1-hd` and both `gpt-4o-mini-tts` snapshots on 2026-10-01; shutdown 2027-01-06; the named replacement `gpt-realtime-2.1-mini` serves only the realtime WebSocket | [9], [10] | high |
| OpenAI `/audio/speech` `pcm` is raw 24 kHz signed 16-bit little-endian; voices `marin` and `cedar` are recommended; `instructions` steers tone and accent | [11] | high (mono: medium) |
| ElevenLabs `/v1/text-to-speech/{voice_id}/stream?output_format=pcm_24000` streams S16LE; `eleven_flash_v2_5` (~75 ms) and `eleven_multilingual_v2` cover pt-BR; `eleven_v4` models (2026-09-28) are routed through Text to Dialogue | [12], [13], [14] | high (v4 on the stream endpoint: low) |
| `sounddevice` 0.5.6 bundles PortAudio on macOS; `RawOutputStream(dtype="int16")` takes plain bytes | [15] | high |

## Implications

- The port yields int16 mono PCM chunks with their sample rate; every adapter converts to it (Kokoro float32, the others already int16).
- The bench reports time to first audio and total synthesis time separately: for `say`, and for one sentence on Kokoro or Piper, they are equal.
- `say` is the dependency-free local default; Kokoro and Piper are optional extras, so a default install carries no GPL code.
- The OpenAI adapter on `/audio/speech` lives until 2027-01-06; its replacement is a separate issue. Model ids sit in configuration, never in code.

## Open Questions

- pt-BR quality and speed of each voice on this machine: the bench answers it.
- Whether `eleven_v4_turbo` works on the plain stream endpoint.
- Whether an ElevenLabs account has pt-BR voices, or one must be added from the shared library first.

# References

[1] [say(1) man page](https://ss64.com/mac/say.html). Available at: https://ss64.com/mac/say.html. Accessed on: 2026-10-07.
[2] [kokoro-onnx on PyPI](https://pypi.org/project/kokoro-onnx/). Available at: https://pypi.org/project/kokoro-onnx/. Accessed on: 2026-10-07.
[3] [kokoro-onnx source](https://github.com/thewh1teagle/kokoro-onnx). Available at: https://github.com/thewh1teagle/kokoro-onnx. Accessed on: 2026-10-07.
[4] [kokoro-onnx model files v1.1](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1). Available at: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1. Accessed on: 2026-10-07.
[5] [kokoro on PyPI](https://pypi.org/project/kokoro/). Available at: https://pypi.org/project/kokoro/. Accessed on: 2026-10-07.
[6] [misaki espeak loader](https://github.com/hexgrad/misaki/blob/main/misaki/espeak.py). Available at: https://github.com/hexgrad/misaki/blob/main/misaki/espeak.py. Accessed on: 2026-10-07.
[7] [piper1-gpl](https://github.com/OHF-Voice/piper1-gpl). Available at: https://github.com/OHF-Voice/piper1-gpl. Accessed on: 2026-10-07.
[8] [Piper pt_BR voices](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR). Available at: https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR. Accessed on: 2026-10-07.
[9] [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations). Available at: https://developers.openai.com/api/docs/deprecations. Accessed on: 2026-10-07.
[10] [gpt-realtime-2.1-mini](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini). Available at: https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini. Accessed on: 2026-10-07.
[11] [OpenAI text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech). Available at: https://developers.openai.com/api/docs/guides/text-to-speech. Accessed on: 2026-10-07.
[12] [ElevenLabs stream endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/stream). Available at: https://elevenlabs.io/docs/api-reference/text-to-speech/stream. Accessed on: 2026-10-07.
[13] [ElevenLabs models](https://elevenlabs.io/docs/models). Available at: https://elevenlabs.io/docs/models. Accessed on: 2026-10-07.
[14] [ElevenLabs changelog 2026-09-28](https://elevenlabs.io/docs/changelog/2026/9/28). Available at: https://elevenlabs.io/docs/changelog/2026/9/28. Accessed on: 2026-10-07.
[15] [python-sounddevice](https://github.com/spatialaudio/python-sounddevice). Available at: https://github.com/spatialaudio/python-sounddevice. Accessed on: 2026-10-07.
