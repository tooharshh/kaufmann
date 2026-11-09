# Browser shopping evaluation

`data/evaluation/intents.jsonl` contains 80 authored intent cases: twenty behaviors in English, Telugu script, Romanized Telugu and mixed language. They cover budgets, ranges, negation, corrections, paging, rejection, comparisons, ordinals, quantity operations, delivery proposals and memory. Telugu expectations require bilingual review before they are considered release evidence. These cases are development scenarios; do not call them held-out benchmarks after using them to adjust prompts.

Run schema validation without provider calls:

```sh
uv run python scripts/evaluate_intents.py --output /tmp/intents-validation.json
```

Run a bounded real-model evaluation against the existing Cerebras configuration:

```sh
uv run python scripts/evaluate_intents.py --live --limit 80 --delay 12 --output /tmp/intents-live.json
```

The runner uses the actual phase prompts and tool schemas, seeded application context and simulated tool responses. It never invokes commerce tools or speech. It evaluates tool selection and selected argument constraints, not end-to-end ordering, recommendation relevance, audio quality or memory-extraction precision. First-tool timing measures the tool decision, not browser playback. First-token timing stays null when no text token was emitted. Provider errors are reported separately without retrying failed cases until they pass. The initial twelve-second spacing can still hit provider quotas when one case needs several model calls; increase spacing for a subsequent separately identified run. Keep failed/error cases in the original report.

`data/evaluation/browser-audio.json` defines twenty multi-turn browser workflows. Record them using test accounts and disposable catalogs, including English, Telugu and switching language within a sentence. Use `?voice_debug=1` in the browser to collect playback estimates through `kaufmannVoiceMetrics()`. Worker latency logs distinguish model first text, TTS first audio, application stages and SDK turn latency. Recordings and manual judgments are required; workflow definitions alone are not successful audio tests.

Store a WAV recording and one JSON trace per scenario under a private evidence directory. Name the trace `SCENARIO_ID.json`. For example:

```json
{
  "scenario_id": "audio-01-complete_order",
  "language": "mixed",
  "recording_path": "complete-order.wav",
  "review": {
    "reviewer": "reviewer identifier",
    "application_verified": true,
    "telugu_verified": true
  },
  "checks": {
    "no_unauthorized_order": true,
    "no_cross_user_disclosure": true,
    "no_silent_budget_violation": true,
    "no_false_success": true
  },
  "judgments": {
    "relevant_recommendations": 2,
    "recommendations": 3,
    "satisfied_constraints": 5,
    "checked_constraints": 5,
    "repeated_recommendations": 0,
    "correct_memories": 1,
    "recalled_memories": 1,
    "completed_task": true
  },
  "turns": [
    {"response_ms": 1200, "first_token_ms": 350, "first_audio_ms": 700, "browser_playback_start_ms": 950}
  ]
}
```

The numbers above illustrate the format; they are not measured results. Use timings relative to the same observed end of user speech. Keep raw latency events as supporting evidence and label browser playback values as estimates. Do not substitute request duration or first-tool timing for first audio.

```sh
uv run python scripts/evaluate_audio.py --evidence-dir /path/to/private/evidence --output /tmp/audio-report.json
```

The audit checks WAV presence and duration, scenario identity, application verification, bilingual review for Telugu/mixed speech, explicit safety judgments and bounded numeric metrics. It reports missing evidence and missing timings, aggregates p50/p95, and calculates relevance, constraint accuracy, repeated recommendations, task completion and memory precision from supplied human judgments. It does not listen to recordings or independently verify a reviewer's assertions. All twenty workflows must have reviewed evidence, complete timing categories and passing safety checks for its release gates to pass. A zero denominator produces null, never perfect precision.

Regular regression verification:

```sh
uv run pytest
uv run ruff check .
RUN_BROWSER_TESTS=1 bash scripts/test_database.sh
```

The last command needs disposable local Docker PostgreSQL and Chrome CDP on port 9223. Its browser SDK is stubbed: this proves browser/commerce wiring, not live speech quality. The browser regression exercises Profile memory correction/forgetting; database tests separately cover ownership, catalog isolation, unknown inventory, immutable imported rows and discovery expiry/reconnects.

## Selective-memory extraction

`data/evaluation/memory.jsonl` contains twenty authored source turns across the four language forms. Run `uv run python scripts/evaluate_memory.py --live --limit 20 --delay 20 --output /tmp/memory-live.json` to evaluate the actual extraction request and production retention gate without writing any user memory. Without `--live`, cases are marked not_run. The report distinguishes provider errors from successful empty extraction and reports exact case matches, precision and recall. This checks extraction selectivity, not cross-session database persistence; database/browser tests cover the latter separately. Telugu labels still need bilingual review.

The tool-intent runner supports repeated `--group` options for separately identified focused checks. It uses the live request aids, source-amount guard and memory fact validation, retaining raw and canonical arguments and rejected attempts in the trace. Do not combine a repaired-group recheck into the original whole-suite score.
