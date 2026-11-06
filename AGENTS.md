# AGENTS.md

Voice AI shopping assistant for a store with a conventional e-commerce web UI. It converses in English and Telugu (including mid-sentence switching) and supports product discovery, comparison, cart edits, substitutions, and explicit order confirmation. Built on LiveKit Agents (Python), Sarvam for speech, and a database for persistence. Deployed on Render.

Design rationale lives in `docs/ARCHITECTURE.md`. Read it before changing agent handoffs, state, or the order flow. Do not duplicate it here.

## Commands

Use `uv` for everything Python. Never use `pip` directly.

- Install: `uv sync`
- Download models (first run only): `uv run python src/agent.py download-files`
- Talk to the agent in the terminal: `uv run python src/agent.py console`
- Run for the web app: `uv run python src/agent.py dev`
- Production: `uv run python src/agent.py start`
- Tests: `uv run pytest`
- Lint and format: `uv run ruff check .` and `uv run ruff format .`
- Seed the catalog: `uv run python scripts/seed_catalog.py`
- Web app: see `web/README.md` (TODO: fill in install and dev commands)

Before finishing any task, run the tests and the linter.

## Layout

- `src/agent.py`: worker entrypoint and session setup
- `src/agents/`: concierge, shopping advisor, cart and checkout agents
- `src/tools/`: function tools exposed to the LLM
- `src/engine/`: cart, pricing, budget, and order logic (deterministic, no LLM)
- `src/state/`: session state and persistence
- `src/catalog/`: product data access and search
- `src/db/`: database models and migrations
- `web/`: store frontend
- `data/`: catalog seed data
- `tests/`: unit and conversation tests

## Hard rules

- The engine is the source of truth. Prices, totals, stock, and budget checks come from tool results, never from the model's memory or arithmetic.
- An order may only be placed through the confirmation gate. `prepare_order` returns a read-back summary and a pending token. `confirm_order` only works if that token exists and the cart has not changed since. Any cart change clears the token.
- Session state is persisted after every tool call and turn, and reloaded on reconnect. Do not keep state only in memory.
- Standing instructions from the user (for example "keep answers short") are stored in state and injected into every turn. They must survive agent handoffs.
- Handoffs pass state, not chat history. Keep one voice and do not announce transfers to the user.
- Every tool returns a structured result with an explicit status (`ok`, `out_of_stock`, `over_budget`, `not_found`, and so on) so the model reacts to facts.
- Cart changes from the web UI go through the same engine as voice, and the agent is told about them on its next turn.

## Spoken output

Agent replies are heard, not read.

- Short sentences. No markdown, lists, emoji, or symbols.
- Say numbers and prices naturally ("nine hundred rupees").
- Calm and professional. No exaggerated enthusiasm and no repeated acknowledgments. Vary or skip them.
- Reply in the user's most recent language and mirror their mixing of Telugu and English. Use `name_te` for Telugu product names.
- Ask at most one clarifying question, and only when the answer changes the result. Prefer to search first with sensible defaults.
- Keep prompts in `src/agents/` modular. Category-specific guidance (electronics, grocery, fashion) is a short prompt module loaded on demand.

## Voice pipeline

- Speech: Sarvam STT with auto language detection and Sarvam TTS (Bulbul). Follow Sarvam's LiveKit guidance: `flush_signal=True`, `turn_detection="stt"`, and a small `min_endpointing_delay`.
- Pin `livekit-agents` and plugin versions. Plugin docs differ between versions, so check the installed version's docs before changing STT or TTS settings.
- On interruption, stop speech immediately and truncate history to what was actually spoken.
- Keep time-to-first-audio low. Stream LLM output into TTS, and do not add blocking calls to the turn path.

## Configuration and secrets

- Environment variables: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `SARVAM_API_KEY`, `DATABASE_URL`, and the LLM provider key. Document new ones in `.env.example`.
- Never commit `.env`, keys, or tokens. Never print secrets in logs.
- Render exposes HTTP only. Do not add anything that needs raw UDP ports on Render. The agent connects outbound to LiveKit Cloud.

## Testing

- Add tests for any change to the engine, confirmation gate, or state handling.
- Test conversation behavior as text where possible: budget changes, quantity corrections, substitutions, reference resolution ("the second one"), and a "wait" at the confirmation step.

## Boundaries

Ask first:
- Database schema changes or migrations
- Adding or upgrading dependencies
- Changing the STT, TTS, or LLM provider or model
- Changing confirmation, cart, or handoff logic

Never:
- Edit or commit `.env`
- Run destructive database commands against a shared or production database
- Let the model state a price, total, or stock level that did not come from a tool
- Bypass the confirmation gate, even in tests or demos

## Working style

- Make small, focused changes. Do not refactor unrelated code.
- State assumptions briefly when requirements are unclear, and ask when a choice would be hard to reverse.
