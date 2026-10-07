---
type: Issue
title: The repository skeleton, the sidecar toolchain and the CI gates are green with no voice behavior yet
description: "Slice 1: repository files after claude-code-mode, a uv sidecar package that prints its version, se-gates and CI green."
owner: Evaldo Klock
status: open
timestamp: 2026-10-07T19:48:19Z
---

## 0001. The repository skeleton, the sidecar toolchain and the CI gates are green with no voice behavior yet

Lays the repository out after `claude-code-mode` and proves both toolchains run under the gates before any voice code exists. Implements the layout of [ADR 0001](/adr/0001-a-claude-code-mod-drives-a-python-sidecar-daemon-that-holds-the-audio-over-a-json-lines-event-stream-and-a-unix-socket-command-channel-with-speech-providers-behind-ports.md).

### Scope

- Root files: `CLAUDE.md`, `README.md` (status: pre-alpha, no install step yet), `LICENSE` (MIT), `.gitignore`, `se-gates.config.json`.
- `.claude-plugin/plugin.json` (exists) and `.claude-plugin/marketplace.json`, so the repository is its own marketplace.
- `sidecar/`: a `uv` project with a `voice_sidecar` package (src layout) whose console script `voice-sidecar --version` prints the version, its tests, and a committed `uv.lock`.
- `.github/workflows/ci.yml` and `release.yml`.
- The living docs: constitution, ADR 0001, issues 0001 to 0005, indexes.

### Decision

- **Python 3.12**, pinned in `sidecar/.python-version`, not the machine's 3.14: the local speech stack (Kokoro and its torch, onnxruntime for openWakeWord) ships wheels for new Python versions late. Issue 0002 confirms or moves it.
- **Sidecar tooling:** `ruff` for lint and format, `mypy --strict`, `pytest`, all in the `dev` dependency group. `pyright` was the option not taken; `mypy` runs in CI with no Node.
- **One version, three places:** `plugin.json`, `sidecar/pyproject.toml` and the release tag agree; a sidecar test and the release workflow hold them together.
- **No Node toolchain and no hooks module yet.** `package.json`, the TypeScript config, `hooks/` and `install.sh` arrive with the first hooks module in issue 0004; until then CI checks the plugin with `claude plugin validate .` alone.
- **CI runs on `ubuntu-latest`** for now; a job moves to `macos-latest` when an adapter needs macOS.

### Acceptance

- `uv run --project sidecar voice-sidecar --version` prints `0.1.0`, the version in `.claude-plugin/plugin.json`.
- A sidecar test fails when the package version and `plugin.json` disagree.
- In `sidecar/`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` and `uv run pytest` pass.
- `claude plugin validate .` passes, marketplace included.
- `se-gates check` passes with `se-gates.config.json` in blocking mode.
- `living-docs check docs` passes.
- `ci.yml` runs the sidecar checks and the plugin validation on push to `main` and on pull requests; `release.yml` refuses a tag that differs from either version.
