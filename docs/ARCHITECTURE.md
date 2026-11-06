# Architecture outline

This outline records the constraints in AGENTS.md. It describes the intended system, not implemented behavior. Detailed technology and interface decisions remain pending.

## Shared commerce engine

Voice tools and web cart actions use the same deterministic engine. Catalog and engine results supply all prices, stock, totals, and budget decisions. LLM-facing tools return structured results with explicit statuses.

## Order confirmation

The intended confirmation gate uses `prepare_order` to return a read-back summary and pending token. `confirm_order` requires a valid token and an unchanged cart. Every cart mutation invalidates the token. No checkout behavior is implemented in this skeleton.

## Sessions and agents

Persist session state after each tool call and turn, and reload it on reconnect. State includes standing instructions and is passed through handoffs without transferring chat history. Web cart changes must be visible to the voice agent on its next turn.

## Voice and deployment

The planned worker uses LiveKit Agents and Sarvam speech, with English/Telugu language mixing and streamed responses. Interruptions stop speech and truncate history to spoken content. Render hosts the application over HTTP; the worker connects outbound to LiveKit Cloud.

## Decisions pending

LiveKit Agents and the Sarvam plugin are pinned in `pyproject.toml` and `uv.lock`. A Python 3.11 Docker image provides the runtime environment. The LLM provider and model, database and schema, frontend framework, API contracts, and Render service configuration have not been selected. Provider, schema, dependency, and commerce-flow changes require the approvals described in AGENTS.md.
