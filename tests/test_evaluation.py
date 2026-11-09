import asyncio
import json
from pathlib import Path
from uuid import uuid4

from src.evaluation.intents import load_cases, score_case, summarize
from src.state.memory import MemoryQueue


def test_evaluation_scenarios_cover_four_language_forms_and_twenty_audio_flows():
    cases = load_cases(Path("data/evaluation/intents.jsonl"))
    assert len(cases) == 80
    assert {c["language"] for c in cases} == {"en", "te", "te-Latn", "mixed"}
    groups = {c["group"] for c in cases}
    assert len(groups) == 20
    assert all(sum(c["group"] == group for c in cases) == 4 for group in groups)
    audio = json.loads(Path("data/evaluation/browser-audio.json").read_text())
    assert len(audio) == 20 and len({c["id"] for c in audio}) == 20
    assert all(len(c["steps"]) >= 3 and c["human_review"] == "pending" for c in audio)


def test_intent_scoring_rejects_unsafe_extra_actions_and_preserves_missing_metrics():
    case = {"expected": {"tool": "search_products", "args": {"max_price_paise": 50000}}}
    call = {"name": "search_products", "arguments": {"max_price_paise": 50000}}
    assert score_case(case, [call])["passed"]
    assert not score_case(case, [call, {"name": "confirm_order", "arguments": {}}])[
        "passed"
    ]
    assert not score_case(case, [{**call, "arguments": {"max_price_paise": 500000}}])[
        "passed"
    ]
    report = summarize([{"status": "not_run"}])
    assert report["intent_accuracy"] is None and report["task_completion"] is None
    assert report["latency_ms"]["first_token_ms"]["p50"] is None


def test_memory_queue_ignores_malformed_candidates_and_keeps_processing():
    class Memory:
        def __init__(self):
            self.saved = []

        async def change(self, *args, **kwargs):
            self.saved.append(args)
            return {"status": "ok", "changed": True}

    async def run():
        memory = Memory()

        async def extract(text):
            if text == "malformed":
                return [None, "bad", {"stable": "yes", "evidence": text}]
            return [
                {
                    "stable": True,
                    "evidence": text,
                    "fact": {
                        "subject": "self",
                        "scope": "clothing",
                        "key": "size",
                        "value": "medium",
                    },
                }
            ]

        queue = MemoryQueue(memory, extract)
        queue.submit("malformed", uuid4(), 0)
        queue.submit("I usually wear medium", uuid4(), 0)
        async with asyncio.timeout(2):
            await queue.queue.join()
        assert len(memory.saved) == 1
        await queue.close()

    asyncio.run(run())


def test_audio_audit_never_promotes_missing_recordings_to_success(tmp_path):
    from src.evaluation.audio import audit_audio

    report = audit_audio(Path("data/evaluation/browser-audio.json"), tmp_path)
    assert report["planned"] == 20 and report["reviewed"] == 0
    assert report["release_gates_passed"] is False
    assert report["latency_ms"]["first_audio_ms"]["p50"] is None
    assert report["metrics"]["relevance"] is None


def test_scope_retrieval_understands_common_product_words_without_a_model_call():
    from src.state.memory import scope_matches

    assert scope_matches("clothing", "Show blue shirts")
    assert scope_matches("clothing", "నీలం షర్టులు చూపించు")
    assert scope_matches("footwear", "Cheppulu kavali")
    assert not scope_matches("clothing", "Show phones")


def test_audio_audit_requires_human_review_and_actual_recording(tmp_path):
    import wave

    from src.evaluation.audio import GATES, TIMINGS, audit_audio

    scenario = {"id": "one", "languages": ["en", "te"]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([scenario]))
    with wave.open(str(tmp_path / "sample.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(32000))
    trace = {
        "scenario_id": "one",
        "language": "te",
        "recording_path": "sample.wav",
        "review": {"reviewer": "test-reviewer", "application_verified": True},
        "checks": dict.fromkeys(GATES, True),
        "judgments": {
            "relevant_recommendations": 1,
            "recommendations": 2,
            "satisfied_constraints": 3,
            "checked_constraints": 3,
            "repeated_recommendations": 0,
            "correct_memories": 1,
            "recalled_memories": 1,
            "completed_task": True,
        },
        "turns": [dict.fromkeys(TIMINGS, 120)],
    }
    evidence = tmp_path / "one.json"
    evidence.write_text(json.dumps(trace))
    assert audit_audio(manifest, tmp_path)["results"][0]["status"] == "invalid_evidence"
    trace["review"]["telugu_verified"] = True
    evidence.write_text(json.dumps(trace))
    report = audit_audio(manifest, tmp_path)
    assert report["metrics"]["relevance"] == 0.5
    assert report["latency_ms"]["first_audio_ms"]["p95"] == 120
    assert report["release_gates_passed"]
    trace["checks"]["no_unauthorized_order"] = False
    evidence.write_text(json.dumps(trace))
    assert not audit_audio(manifest, tmp_path)["release_gates_passed"]


def test_automatic_extraction_never_processes_forget_requests():
    async def run():
        seen = []

        async def extract(text):
            seen.append(text)
            return []

        queue = MemoryQueue(None, extract)
        for text in (
            "Forget my size",
            "నా సైజు మర్చిపో",
            "Naa size marchipo",
            "Don't save my address",
        ):
            queue.submit(text, uuid4(), 0)
        assert queue.queue.empty() and queue.worker is None
        assert seen == []
        await queue.close()

    asyncio.run(run())


def test_preference_storage_rejects_contact_identifiers_even_under_a_valid_key():
    import pytest

    from src.state.memory import validate_fact
    from src.state.session import Refusal

    for value in ("qa@example.test", "+91 9876543210", "500001"):
        with pytest.raises(Refusal):
            validate_fact(
                {"subject": "self", "scope": "general", "key": "brand", "value": value}
            )


def test_recipient_labels_and_clothing_sizes_have_stable_canonical_forms():
    from src.state.memory import validate_fact

    base = {"scope": "clothing", "key": "size", "value": "L"}
    assert validate_fact({**base, "subject": "recipient:annayya"}) == validate_fact(
        {**base, "subject": "recipient:brother"}
    )
    assert validate_fact({**base, "subject": "recipient:అన్నయ్య"})["value"] == "large"


def test_memory_scoring_does_not_reward_storing_one_off_purchases():
    from src.evaluation.memory import score_memory, summarize_memory

    fact = {"subject": "self", "scope": "clothing", "key": "size", "value": "medium"}
    assert not score_memory([], [fact])["passed"]
    report = summarize_memory([{"status": "error"}])
    assert report["memory_precision"] is None and report["provider_errors"] == 1


def test_retention_gate_requires_stability_verbatim_evidence_and_nonsensitive_keys():
    from src.state.memory import validated_candidates

    text = "I usually wear medium."
    fact = {"subject": "self", "scope": "clothing", "key": "size", "value": "medium"}
    assert (
        validated_candidates(text, [{"stable": False, "evidence": text, "fact": fact}])
        == []
    )
    assert (
        validated_candidates(
            text, [{"stable": True, "evidence": "Not in the source", "fact": fact}]
        )
        == []
    )
    assert (
        validated_candidates(
            text,
            [{"stable": True, "evidence": text, "fact": {**fact, "key": "address"}}],
        )
        == []
    )
    repeated = [
        {"stable": True, "evidence": text, "fact": {**fact, "value": v}}
        for v in ("M", "medium")
    ]
    assert validated_candidates(text, repeated) == [fact]


def test_memory_extraction_outage_is_not_a_successful_empty_result():
    import pytest

    from src.state.memory import MemoryExtractionUnavailable, extract_candidates

    class Response:
        status = 429

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class HTTP:
        def post(self, *args, **kwargs):
            return Response()

    async def run():
        with pytest.raises(MemoryExtractionUnavailable):
            await extract_candidates(HTTP(), "test-key", "I usually wear medium.")

    asyncio.run(run())
