# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

@AGENTS.md

`AGENTS.md`, imported above, is the canonical contributor guide for this
repository — full layout, architecture, testing, gotchas, and the Mintlify
docs-versioning system. This file exists so Claude Code loads it automatically,
and adds only the quick reference below. When the two disagree, `AGENTS.md`
wins; fix it there rather than patching around it here.

## Orientation in one paragraph

This is `RJHuey73/crewAI`, a fork of `crewAIInc/crewAI`: a lean,
dependency-light Python framework for role-playing autonomous multi-agent
systems, built from scratch (no LangChain). Two programming models ship side by
side — **Crews** (role-based agent collaboration) and **Flows** (event-driven
orchestration of LLM calls and Crews) — plus the `crewai` CLI. It's a **`uv`
workspace monorepo**: six packages under `lib/` (`crewai`, `crewai-core`,
`crewai-tools`, `crewai-files`, `cli`, `devtools`), each a standalone `src/`-layout
distribution. Most contributions touch `lib/crewai/`.

## The commands you'll actually run

Everything goes through `uv`; **never invoke `pip` directly**.

```bash
uv sync --all-groups --all-extras
uv run pre-commit install

uv run pytest lib/crewai/tests/ -x -q                       # one package
uv run pytest lib/crewai/tests/agents/test_agent.py::test_agent_creation -x -q
uv run pytest .                                             # full workspace

uv run ruff check lib/ && uv run ruff format lib/
uv run mypy lib/                                            # strict, repo-wide
uv add --package crewai <dep>                               # never hand-edit uv.lock
```

Pre-commit runs ruff, mypy, `uv-lock`, and `pip-audit` — don't bypass it with
`--no-verify`.

## Non-negotiables (details in AGENTS.md)

- **Network is blocked in tests** (`--block-network`). HTTP-dependent tests
  replay VCR cassettes; tests run **parallel and randomly ordered**
  (`pytest-xdist` + `pytest-randomly`), so nothing may depend on ordering or
  shared mutable state.
- **`mypy --strict` is repo-wide** (templates and test dirs excluded) and CI
  type-checks Python 3.10–3.13 even though `[tool.mypy]` targets 3.12 — a
  construct that passes locally can still fail CI on another interpreter.
- **`uv.lock`'s `exclude-newer` / `override-dependencies` entries are security
  floors**, each annotated with the CVE/GHSA/PYSEC it pins for. Don't loosen one
  to resolve a version conflict without checking what it's protecting.
- **Conventional Commits** (`<type>(<scope>): <description>`, imperative, ≤72
  chars) are enforced by CI; branches are `<type>/<short-description>`.
- **AI-generated contributions must carry the `llm-generated` label** on the PR
  or issue — unlabeled ones may be closed without review. This applies to work
  done here.
- **Never edit `docs/v*/`** — those are frozen release snapshots guarded by CI.
  Docs edits go in `docs/edge/<lang>/`. `docs/images/` is append-only.
- **The root `pyproject.toml` package is `crewai-workspace`**, not `crewai`.
  There is no top-level `crewai/` import root and no top-level `src/`.
