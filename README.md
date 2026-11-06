# Kaufmann

A store with a conventional e-commerce UI and an English/Telugu voice shopping assistant, including mixed-language conversations. Planned capabilities include product discovery, comparison, cart edits, substitutions, and explicit order confirmation.

This repository is an initial skeleton with a Python environment and container definition. The voice worker, persistence, and frontend are not implemented yet.

## Structure

- `src/agent.py`: LiveKit worker entrypoint and session setup.
- `src/agents/`: concierge, shopping advisor, cart, checkout, and category prompt modules.
- `src/tools/`: structured LLM-facing tool adapters.
- `src/engine/`: deterministic cart, pricing, budget, and order operations shared by voice and web.
- `src/state/`: session state and persistence.
- `src/catalog/`: catalog access and search.
- `src/db/`: database models and future migrations.
- `web/`: store frontend.
- `data/`: catalog seed data.
- `scripts/`: catalog seeding and operational scripts.
- `tests/`: engine, state, tool, and text conversation tests.

Read `AGENTS.md` and `docs/ARCHITECTURE.md` before implementation.

## Python setup

Use Python 3.11 and uv. Runtime dependencies are pinned in `pyproject.toml`; `uv.lock` pins their transitive dependencies. Development dependencies include pytest and Ruff.

```sh
uv venv --python 3.11
uv sync --locked
uv run python --version
uv run pytest
uv run ruff check .
```

`uv run` automatically uses `.venv`. For an interactive shell, use `source .venv/bin/activate`.

## Container

```sh
docker build -t kaufmann:local .
docker run --rm kaufmann:local python -c 'from livekit import agents; from livekit.plugins import sarvam; print("Imports OK")'
```

The image uses Python 3.11, installs locked runtime dependencies without development tools, and runs as a non-root user. Local virtual environments and secret files are excluded from the build context.

The default command is `python src/agent.py start`. It currently exits with an explicit message because the worker is a placeholder. After worker implementation, provide configuration at runtime with `docker run --rm --env-file .env kaufmann:local`. The image does not yet serve HTTP or provide a Render health endpoint; these belong to worker implementation. It does not require inbound UDP ports.

## Configuration

`.env.example` lists configuration names only. Supply real values locally and never commit `.env`. The LLM provider, database technology, and frontend framework remain undecided.
