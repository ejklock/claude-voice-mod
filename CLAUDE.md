# claude-voice-mod

A Claude Code mod for a spoken conversation over an always-open channel, like the Codex CLI's voice mode. The mod is a thin client; a Python sidecar daemon (managed by `uv`) owns the microphone, the speaker and the speech models, behind the ports `SpeechToText`, `TextToSpeech` and `WakeWord`. Started on 2026-10-07.

Start at the [Constitution](docs/constitution.md). The decisions and the open work are in [docs/index.md](docs/index.md).

## Living Docs

```
enforcement: guided   # strict | guided | lite
onboarded: 2026-10-07
```

Write an ADR only when a decision is expensive to reverse; every other decision lives in the issue that carries the work. Load-bearing decisions are confirmed with the owner before an ADR is recorded. `living-docs check docs` must pass; numbering, frontmatter and index rows are CLI-owned (`living-docs new/set/supersede/index/fmt`).

| Artifact | Location |
|---|---|
| Constitution | `docs/constitution.md` |
| ADRs | `docs/adr/` |
| Issues | `docs/issues/` |
| Research | `docs/research/` |

## Commands

| What | Command |
|---|---|
| Sidecar lint, format, types, tests | `cd sidecar && uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest` |
| Plugin manifest and marketplace | `claude plugin validate .` |
| Quality gate | `se-gates check` |
| Docs gate | `living-docs check docs` |

## Hard rules

1. **Audio lives only in the sidecar.** No file under `hooks/` calls `$.audio.speak` or `$.audio.play`.
2. **Local by default.** With no configuration every port runs a local adapter; an external adapter reads its key only from the environment.
3. **Every message across the mod–sidecar boundary is parsed by a schema**, on the side that receives it.
4. **One version in three places:** `.claude-plugin/plugin.json`, `sidecar/pyproject.toml` and the release tag.
5. **All artifacts in English.** Conversation follows the owner's language.
6. **Diagrams are Mermaid.**
7. **The mods API is early access.** Read the installed build's type declarations before using a call; never trust memory of the API.

## Commit authorship

Git `Author` is `Evaldo Klock <neto.nemesis@gmail.com>`.
