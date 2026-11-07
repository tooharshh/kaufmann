# Voice shopping

Start `uv run python -m src.api` and `uv run python -m src.agent dev` in separate terminals. Sign in at http://localhost:8080 and select the microphone. Use headphones to reduce feedback. HTTPS or localhost is required. The pinned SDK's legacy dev command does not hot-reload; restart it after changes.

Production uses `python -m src.agent start`. See [production](production.md) for containers and Render. Console mode lacks signed room authorization and intentionally cannot create shopping sessions.

## Pipeline

Sarvam streaming STT → Cerebras `gpt-oss-120b` → Sarvam Bulbul v3 TTS. Cerebras uses its OpenAI-compatible endpoint through the pinned LiveKit OpenAI plugin. There is no automatic provider fallback. All LiveKit packages are pinned to 1.8.11; the bundled browser SDK is 2.23.0, with its license under `web/vendor/`.

STT streams 50 ms audio chunks with automatic language detection, `flush_signal=True`, STT turn detection and 0.2–3 second endpointing. The installed adapter emits final transcripts rather than incremental interim transcripts. LLM output streams with low reasoning effort, sequential tools and at most six tool steps. HTTP and SDK LLM retries are disabled, with an eight-second SDK connection timeout. Provider failures receive a brief spoken response when TTS remains available.

The response tokenizer emits complete sentences without extra sentence lookahead. It protects decimals, abbreviations and known product names, retains incomplete words and discards unspoken tails on cancellation. Its tokenizer hook uses the pinned Sarvam options dataclass; verify compatibility before upgrading the plugin. Sarvam still applies its server-side minimum buffer of 30 and maximum chunk length of 80. Short phrases can wait for additional text or final flush; unpunctuated text waits for completion. Vendor-internal synthesis boundaries are not guaranteed to match application text boundaries.

TTS connections prewarm without blocking. Audio streams into LiveKit and native browser playback. The first text segment selects English or Telugu synthesis; full code-mixed pronunciation needs listening checks. Interruptions stop playback and truncate SDK history to spoken content.

## Identity, state and confirmation

`POST /api/voice/session` verifies the signed-in Supabase account, creates a short-lived private room token, and dispatches `kaufmann-shopping`. Signed dispatch metadata binds the account, room and expiry. The worker checks it before constructing the user-bound engine and listens only to the expected participant.

Concierge, discovery, basket and checkout agents share persisted runtime state and the current request. Handoffs do not copy old chat. Actual SDK message IDs identify user turns; interrupted or superseded speech cannot mutate the cart. The model never receives approval tokens, delivery receipts or user identity as tool arguments.

The engine prepares a snapshot, generated speech reads it back, and only completed uninterrupted playout records delivery. A later actual user approval must match that unchanged review. An interruption, correction, question or “wait” cannot authorize checkout. Reconnects require a new review. These are the same safeguards used by browser checkout.

## Discovery and presentation

Natural English, Telugu and mixed requests become concrete English product keywords with separate price and metadata filters. Searches prefer sensible defaults, allow at most one meaningful broader retry and preserve explicit constraints. Missing compatibility, age or safety evidence stays unknown.

Recommendation replies are brief; the screen carries product lists. Explicit detail/price questions receive tool-backed facts. Selecting a product asks whether more details are wanted. Successful additions open the cart and briefly summarize its contents. Address corrections patch only provided fields. Authoritative monetary values have deterministic spoken forms.

Shopping-only instructions reject prompt/code/credential extraction and unrelated requests. Catalog text and saved preferences remain untrusted data. These protections reduce risk but do not prove immunity to every prompt injection.

## Screen synchronization

Validated `kaufmann.selection` and `kaufmann.navigation` messages connect the authenticated room to fixed catalog/product/cart views. Arbitrary URLs and chat commands are rejected. Browser events never count as order approval. Navigation queues in the background and coalesces pending destinations, so it does not delay tool completion. Reconnect independently reloads persisted commerce state.

Catalog filter metadata has a five-minute per-instance cache with coalesced loads, defensive copies and no failure caching. Specification parsing runs off the audio loop. Prices and inventory are never cached by this mechanism.

## Observability

Server logs include `voice_latency`, `voice_stage`, `voice_provider` and `voice_stream` records for SDK EOU latency, model first output, TTS first audio, runtime operations and provider requests. They exclude transcripts, addresses, prompts and tool arguments. SDK playback timing is not physical speaker timing.

Browser diagnostics are opt-in: open `/?voice_debug=1` before connecting. `window.kaufmannVoiceMetrics()` returns up to 100 local estimates of speech-end-to-playback latency. RMS thresholds, device gain, overlapping speech and WebRTC jitter affect accuracy. No recordings or transcripts are stored or uploaded. Diagnostics do not reroute native playback or wait for AudioContext permission before connecting.

A three-sample controlled token replay measured first-audio median 911 → 881 ms and p95 1190 → 1221 ms after tokenizer changes. This does not establish improved production microphone latency. Rate limits and Sarvam errors can still cause failures; fresh real microphone sessions are needed after deployment.

## Verification

```sh
bash scripts/test_database.sh
RUN_BROWSER_TESTS=1 bash scripts/test_database.sh
```

Browser tests require isolated Chrome CDP on localhost:9223. Normal tests use scripted providers and disposable PostgreSQL. Explicit opt-in live checks use the existing providers and local shopping fixtures:

```sh
RUN_VOICE_LIVE=1 bash scripts/test_database.sh tests/test_voice.py -k quantity_correction
RUN_ADDRESS_LIVE=1 bash scripts/test_database.sh tests/test_voice.py -k single_address
RUN_DISCOVERY_LIVE=1 uv run pytest tests/test_discovery_intent.py -s
RUN_FILTERS_LIVE=1 uv run pytest tests/test_discovery_intent.py -s
RUN_VOICE_NAV_LIVE=1 bash scripts/test_database.sh tests/test_voice_navigation.py
RUN_NAV_TRANSPORT_LIVE=1 bash scripts/test_database.sh tests/test_voice_navigation.py
uv run python -m scripts.check_voice_scope
```

The scope checker uses synthetic data and writes ignored results under `data/processed/`. Live checks are bounded but consume provider quotas. They are not part of ordinary tests or image builds. Scripted tests verify wiring and confirmation guards, not microphone acoustics or universal language understanding.
