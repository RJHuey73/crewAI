# Contributor guide

This is `RJHuey73/crewAI`, a fork of [`crewAIInc/crewAI`](https://github.com/crewAIInc/crewAI):
a lean, dependency-light Python framework for orchestrating role-playing,
autonomous multi-agent systems. It ships two complementary programming
models — **Crews** (role-based, autonomous agent collaboration) and **Flows**
(event-driven, precise orchestration of LLM calls and Crews) — plus a CLI for
scaffolding, running, and deploying agent projects. It is intentionally built
from scratch and does not depend on LangChain or other agent frameworks.

This file covers the codebase as a whole (layout, commands, architecture,
testing, gotchas). For everything about editing `docs/` specifically — the
Edge/versioned-snapshot Mintlify system — see [Documentation](#documentation)
below; that section is the canonical docs-contributor guide referenced from
`README.md`.

## Layout

This is a **`uv` workspace monorepo** (`[tool.uv.workspace]` in the root
`pyproject.toml`) with six packages under `lib/`:

| Package | Path | Purpose |
|---------|------|---------|
| `crewai` | `lib/crewai/` | The core framework: `Agent`, `Crew`, `Task`, `Flow`, `Process`, `LLM`, tools, knowledge, memory, RAG, the `crewai` CLI. This is what most contributions touch. |
| `crewai-core` | `lib/crewai-core/` | Shared low-level utilities consumed by `crewai` and `cli` — version info, paths, user-data, telemetry, auth providers, printer. No agent/crew logic lives here. |
| `crewai-tools` | `lib/crewai-tools/` | First-party tool integrations (web search, scraping, file/doc parsing, YouTube, etc.) built on `crewai`'s `BaseTool`. |
| `crewai-files` | `lib/crewai-files/` | Multimodal file-input handling (`FileInput`, content-type detection) used by `crewai` for images/audio/PDF inputs — imported lazily/optionally by `crewai.crew`. |
| `cli` | `lib/cli/` | `crewai-cli`, the `crewai` console-script entry point (`crewai = "crewai_cli.cli:crewai"`) — project scaffolding, running, deployment. Depends on `crewai-core`. |
| `devtools` | `lib/devtools/` | Internal, unpublished (`Private :: Do Not Upload`) release tooling — version bumping, git automation, the `devtools release` flow referenced by the docs freeze process. |

Each package is a standalone `src/`-layout Python distribution with its own
`pyproject.toml`, `README.md`, `src/`, and `tests/`. Other top-level paths:

| Path | Purpose |
|------|---------|
| `docs/` | Mintlify-published site (docs.crewai.com) — Edge + versioned snapshots. See [Documentation](#documentation). |
| `conftest.py` | Root pytest config shared by every package's test suite: VCR/cassette setup (`vcr_cassette_dir`, `vcr_config`), aiohttp/vcrpy compat patching, env normalization for cassette matching. |
| `scripts/` | `scripts/docs/*` (one-time/CLI docs-versioning migrations, see Documentation) and `scripts/age90_file_input_runner.py`. |
| `.env.test` | Test-time environment defaults (API keys/placeholders consumed by cassette-backed tests). |
| `uv.lock` | Single lockfile for the whole workspace. |
| `.github/CONTRIBUTING.md` | Human contributor guide (setup, branching, commit style). Note it currently lists only four `lib/` packages — the table above (from `pyproject.toml`'s actual workspace members) is the accurate one; treat `cli` and `crewai-core` as real, current packages. |

## Commands

Everything goes through `uv`; **never invoke `pip` directly** in this repo.

```bash
# One-time setup
uv sync --all-groups --all-extras
uv run pre-commit install

# Lint / format / type-check (run against `lib/`, the workspace source root)
uv run ruff check lib/
uv run ruff format lib/
uv run mypy lib/                              # strict mypy across all packages
uv run mypy lib/crewai/src/crewai/            # a single package

# Tests
uv run pytest lib/crewai/tests/ -x -q
uv run pytest lib/crewai/tests/agents/test_agent.py -x -q
uv run pytest lib/crewai/tests/agents/test_agent.py::test_agent_creation -x -q
uv run pytest lib/crewai-tools/tests/ -x -q
uv run pytest .                               # full workspace (all `testpaths` in pyproject.toml)

# Dependency management (never edit lockfiles by hand)
uv add --package crewai <package>             # runtime dep on a specific package
uv add --dev <package>                        # workspace-wide dev dep
uv sync

# Build / install locally
uv build
uv pip install dist/*.tar.gz
```

Pre-commit runs `ruff` (check + format), `mypy`, `uv-lock`, and `pip-audit`
locally via hooks defined in `.pre-commit-config.yaml`; don't skip it with
`--no-verify`.

## Architecture & conventions

- **Agent / Crew / Task / Process** (`lib/crewai/src/crewai/agent/`,
  `crew.py`, `task.py`, `process.py`) are the Crews programming model:
  `Agent`s (role, goal, backstory, tools, LLM) execute `Task`s, coordinated by
  a `Crew` under a `Process` (`sequential` or `hierarchical`; `consensual` is
  stubbed but not implemented). Crews are commonly declared via YAML config
  (`agents.yaml`/`tasks.yaml`) plus a `@CrewBase`-decorated class under
  `crewai.project`.
- **Flow** (`lib/crewai/src/crewai/flow/`) is the event-driven orchestration
  model — `@start`/`@listen`/`@router` decorated methods, a DSL
  (`flow/dsl/`), persistence (`flow/persistence/`), and a visualization
  layer. Flows can embed Crews natively; this is the recommended model for
  production/enterprise orchestration per the README.
- **Tools** (`lib/crewai/src/crewai/tools/`, and the separate `crewai-tools`
  package) extend `BaseTool` / `CrewStructuredTool`. `crewai-tools` ships
  first-party integrations; project-specific tools typically live alongside
  the Crew/Flow definition.
- **LLM abstraction** (`llm.py`, `llms/providers/`, `llms/hooks/`) wraps
  provider SDKs behind `BaseLLM`/`LLM`, with call-lifecycle hooks in
  `hooks/llm_hooks.py`.
- **Knowledge / Memory / RAG** (`knowledge/`, `memory/`, `rag/`) provide
  retrieval-augmented context and long-lived agent memory, with pluggable
  backends (`rag/chromadb/`, `rag/qdrant/`, LanceDB via the lazily-imported
  `Memory` class — see `crewai/__init__.py`'s `_LAZY_IMPORTS`).
- **`crewai/__init__.py` does real work at import time**: it lazily imports
  heavy modules (e.g. `Memory` → `lancedb`) via `__getattr__`, then forces
  `model_rebuild()` on several Pydantic models (`Agent`, `Crew`, `Flow`,
  `Task`, `RuntimeState`, executors, `A2A*` configs when present) to resolve
  forward references across a hand-assembled `_types_namespace`. If you add a
  new top-level model with forward refs into `Agent`/`Crew`/`Flow`, wire it
  into this namespace-building block rather than assuming Pydantic will
  resolve it unaided.
- **A2A** (`a2a/`) implements Agent-to-Agent protocol client/server support
  (auth, extensions, updates) and is imported defensively (`try`/`except
  ImportError`) since it's an optional surface.
- **CLI** (`lib/crewai/src/crewai/cli/` for framework-level CLI pieces like
  templates, plus the `lib/cli/` package for the actual `crewai` console
  script) drives `crewai create`, `crewai run`, deployment, etc.
- **Code style** (from `.github/CONTRIBUTING.md` and `pyproject.toml`'s ruff
  config): built-in generics (`list[str]`, `dict[str, int]`, `X | None`), not
  `typing.List`/`Optional`; full type annotations everywhere (`mypy --strict`
  is enforced repo-wide except templates/test dirs); Google-style docstrings;
  `collections.abc` for abstract base classes; prefer `isinstance`/`TypeIs`/
  `TypeGuard` over `hasattr` for type narrowing; absolute imports only
  (`ban-relative-imports = "all"`).
- **Conventional Commits** are required (`<type>(<scope>): <description>`,
  imperative mood, ≤72-char title) — enforced by `commitizen` config and PR
  title CI (`pr-title.yml`). Branch names follow `<type>/<short-description>`.

## Testing

- Pytest across the whole workspace; `testpaths` in the root `pyproject.toml`
  lists every package's `tests/` dir. Each package's tests mirror its `src/`
  layout.
- **Network is blocked by default** (`--block-network` in `addopts`). HTTP-
  dependent tests (LLM calls, tool integrations) replay recorded VCR
  cassettes via `pytest-recording`; `conftest.py`'s `vcr_cassette_dir`
  mirrors each test module's path under a per-package `tests/cassettes/`
  dir. Set `PYTEST_VCR_RECORD_MODE` to re-record; CI forces `record_mode:
  "none"`. `.env.test` supplies placeholder credentials cassette matching
  relies on.
- Tests run in parallel by default (`pytest-xdist`, `-n auto`,
  `--dist=loadfile`) and are randomly ordered (`pytest-randomly`) — don't
  rely on cross-test ordering or shared mutable state.
- The `telemetry` marker (`markers = ["telemetry: ..."]`) opts a test out of
  the default telemetry-mocking behavior — use it only for tests that
  specifically exercise telemetry.
- Per-package pytest ignores in `pyproject.toml`'s
  `[tool.ruff.lint.per-file-ignores]` (e.g. allowing bare `assert`,
  hardcoded-password-looking constants) apply only inside each package's
  `tests/**` — don't lean on those relaxations in library code.
- CI (`tests.yml`) runs the matrix across Python 3.10–3.13, sharded into 8
  groups per version (`pytest-split`), and skips entirely for doc/markdown-
  only changes (`paths-filter`). `type-checker.yml` runs mypy across the same
  Python versions.

## Gotchas

- **This repo's `pyproject.toml` root package is `crewai-workspace`**, not
  `crewai` — the installable `crewai` package lives at `lib/crewai/`. Don't
  expect a top-level `crewai/` import root or a top-level `src/`.
- **`uv.lock` supply-chain pinning is deliberate and load-bearing.**
  `[tool.uv]` sets `exclude-newer = "3 days"` plus per-package
  `exclude-newer-package` overrides and a long `override-dependencies` list,
  each with an inline comment citing the CVE/GHSA/PYSEC it's forcing a
  minimum version for. Don't loosen or remove one of these without checking
  whether it's a security floor, not just a compatibility pin.
- **AI-generated contributions must carry the `llm-generated` label** on any
  PR or issue (per `.github/CONTRIBUTING.md`) — this applies to code, docs,
  and issues alike; unlabeled AI-generated contributions may be closed
  without review.
- **`crewai-files` is an optional/soft dependency of `crewai`** — `crew.py`
  imports it inside a `try`/`except ImportError` and gates on
  `HAS_CREWAI_FILES`. Don't assume multimodal file-input support is always
  present.
- **`mypy` targets Python 3.12** (`python_version = "3.12"` in
  `[tool.mypy]`) even though the workspace supports 3.10–3.13 and CI type-
  checks across that whole range — a 3.12-only construct that mypy accepts
  locally can still fail CI on other interpreters.
- **Templates and generated code are excluded from lint/type-check**:
  `lib/crewai/src/crewai/cli/templates/` and `lib/cli/src/crewai_cli/templates/`
  are excluded from ruff, mypy, and bandit — don't expect them to pass the
  same strict checks as the rest of the codebase.
- **Version pins are workspace-wide and interdependent**: `crewai-tools` and
  `lib/cli` pin exact versions of `crewai`/`crewai-core` (e.g.
  `crewai==1.14.8a5`) rather than ranges — bumping `crewai`'s version without
  updating these sibling pins will desync the workspace.

## Documentation

The `docs/` directory is published at [docs.crewai.com](https://docs.crewai.com)
by [Mintlify](https://www.mintlify.com/). Mintlify watches `docs/docs.json`
and the MDX files referenced from it.

### TL;DR for editing docs

- Edit MDX under `docs/edge/<lang>/...` (e.g. `docs/edge/en/concepts/agents.mdx`).
- Your change ships under the **Edge** version selector the moment it merges
  to `main`. Edge follows `main` and is the channel for unreleased work.
- On release cut, the current Edge state is frozen into `docs/v<X.Y.Z>/` and
  that snapshot becomes the new default version in the selector (tag:
  `Latest`). Canonical URLs (`/<lang>/...`) auto-redirect to the new default.
- Never modify files under `docs/v*/`. Those are frozen release snapshots
  and the `docs-snapshots` CI guard rejects writes. The only exception is a
  release-cut PR (auto-generated by `devtools release` or the manual
  `scripts/docs/freeze_current_edge.py` wrapper), which uses a
  `[docs-freeze]` title prefix to opt out.
- Never delete or rename files under `docs/images/`. Images are append-only.
  See [Images](#images) below.

### The version model

The site has one rolling channel (Edge) plus one frozen snapshot per
release.

```
docs/
  edge/                  <-- Edge sources (you edit here)
    en/...
    pt-BR/  ko/  ar/
    enterprise-api.*.yaml

  v1.14.7/               <-- frozen snapshot of v1.14.7
    en/...
    pt-BR/  ko/  ar/
    enterprise-api.*.yaml
  v1.14.6/...
  ...

  images/                <-- shared, append-only
  docs.json              <-- Mintlify config: navigation + redirects
```

`docs/docs.json` lists one navigation block per version per language. Edge
points at `docs/edge/<lang>/...`; every other version points at its own
`docs/v<X.Y.Z>/<lang>/...` subtree. Mintlify scopes both the sidebar and the
in-site search to whichever version the reader selects, so picking
`v1.10.0` genuinely shows the v1.10.0 docs (and only those).

#### URLs and canonical redirects

Each Mintlify version corresponds to its own URL prefix:

- Edge: `/edge/<lang>/<page>` (e.g. `/edge/en/concepts/agents`)
- Frozen: `/v<X.Y.Z>/<lang>/<page>` (e.g. `/v1.14.7/en/concepts/agents`)

External links to the old, unversioned `/<lang>/<page>` URLs would 404 under
this layout. To keep them working, `docs.json` ships wildcard redirects:

```jsonc
{ "source": "/en/:slug*", "destination": "/v1.14.7/en/:slug*", "permanent": false }
```

The release-cut step rewrites the destination on every release so canonical
`/<lang>/...` URLs always resolve to the latest stable docs.

### Lifecycle

1. **During development.** You add or edit pages under
   `docs/edge/<lang>/...` in normal PRs. They land in Edge as soon as the PR
   merges. Both `/edge/<lang>/<page>` and the version selector's `Edge` entry
   reflect the change immediately.
2. **Release cut.** The release engineer runs `devtools release X.Y.Z`. As
   part of that flow the CLI opens a `[docs-freeze]` PR that copies Edge into
   `docs/v<X.Y.Z>/`, rewrites internal OpenAPI references, updates
   `docs/docs.json` to make `v<X.Y.Z>` the new default + `Latest`, and rewires
   the canonical-URL redirects to the new default. The PR must merge before
   the tag and PyPI publish run.
3. **After release.** Edge keeps rolling. Patch fixes to the just-released
   docs go into Edge and ship with the next release. We do not back-edit
   frozen snapshots.

See [`RELEASING.md`](RELEASING.md) for the full release runbook.

### Images

Snapshots share a single `docs/images/` directory. If an image is deleted
or renamed, every frozen snapshot that referenced it breaks. So the rule
is:

- Adding new images is always fine.
- Deleting or renaming an existing image fails CI unless the PR is a
  `[docs-freeze]` release-cut PR.
- If an asset is wrong, add a new file with a new name and reference the
  new name in the Edge MDX (`docs/edge/<lang>/...`). Leave the old file
  alone.

### Local preview

Install the Mintlify CLI and run from `docs/`:

```bash
npm i -g mintlify
mintlify dev
```

Use the version selector at the top of the rendered page to switch between
Edge and frozen versions.

To check links across every version:

```bash
mintlify broken-links
```

CI runs the broken-links check on every PR that touches `docs/**` via
[`.github/workflows/docs-broken-links.yml`](.github/workflows/docs-broken-links.yml).

### Scripts

- `scripts/docs/freeze_historical_versions.py` — one-time migration that
  reconstructed `docs/v1.10.0/` through `docs/v1.14.7/` from git tags. You
  should not need to run this again.
- `scripts/docs/prefix_version_paths.py` — one-time migration that switched
  `docs/docs.json` to directory-based versioning, inserted Edge, and added
  the canonical-URL redirects. You should not need to run this again.
- `scripts/docs/freeze_current_edge.py` — thin CLI wrapper around
  `crewai_devtools.docs_versioning.freeze`. `devtools release` calls the
  same module during its docs PR step; this script is the manual escape
  hatch (e.g. retroactively freezing a forgotten release).

### CI guards

- [`.github/workflows/docs-snapshots.yml`](.github/workflows/docs-snapshots.yml)
  enforces the two rules above (frozen snapshots immutable, images
  append-only). Both checks accept the `[docs-freeze]` PR-title escape
  hatch.
- [`.github/workflows/docs-broken-links.yml`](.github/workflows/docs-broken-links.yml)
  runs `mintlify broken-links` against the whole site, so adding a new
  page or moving a snapshot file that breaks a link will fail CI.
