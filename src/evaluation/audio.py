"""Aggregate recorded browser evidence without treating missing audio as a pass."""

import json
import wave
from pathlib import Path

from src.evaluation.intents import percentile

GATES = (
    "no_unauthorized_order",
    "no_cross_user_disclosure",
    "no_silent_budget_violation",
    "no_false_success",
)
TIMINGS = (
    "response_ms",
    "first_token_ms",
    "first_audio_ms",
    "browser_playback_start_ms",
)
COUNTS = {
    "relevance": ("relevant_recommendations", "recommendations"),
    "constraint_accuracy": ("satisfied_constraints", "checked_constraints"),
    "repeat_rate": ("repeated_recommendations", "recommendations"),
    "memory_precision": ("correct_memories", "recalled_memories"),
}


def audit_audio(manifest_path: Path, evidence_dir: Path):
    scenarios = json.loads(manifest_path.read_text())
    results, timings, counts, completed = (
        [],
        {k: [] for k in TIMINGS},
        {k: [0, 0] for k in COUNTS},
        [],
    )
    for scenario in scenarios:
        result = {"id": scenario["id"], "status": "missing_evidence"}
        trace_path = evidence_dir / (scenario["id"] + ".json")
        if not trace_path.is_file():
            results.append(result)
            continue
        try:
            trace = json.loads(trace_path.read_text())
            if (
                trace.get("scenario_id") != scenario["id"]
                or trace.get("language") not in scenario["languages"]
            ):
                raise ValueError("invalid_identity")
            recording = evidence_dir / trace["recording_path"]
            with wave.open(str(recording), "rb") as audio:
                if audio.getnframes() <= 0 or audio.getframerate() <= 0:
                    raise ValueError("empty_audio")
                duration = audio.getnframes() / audio.getframerate()
            review = trace["review"]
            if (
                not isinstance(review.get("reviewer"), str)
                or not review["reviewer"].strip()
                or review.get("application_verified") is not True
            ):
                raise ValueError("review_required")
            if trace["language"] != "en" and review.get("telugu_verified") is not True:
                raise ValueError("bilingual_review_required")
            gates = trace["checks"]
            if any(type(gates.get(key)) is not bool for key in GATES):
                raise ValueError("gate_judgments_required")
            judgments = trace["judgments"]
            validated_counts = {}
            for metric, (numerator, denominator) in COUNTS.items():
                n, d = judgments[numerator], judgments[denominator]
                if type(n) is not int or type(d) is not int or not 0 <= n <= d <= 10000:
                    raise ValueError("invalid_counts")
                validated_counts[metric] = (n, d)
            if type(judgments["completed_task"]) is not bool:
                raise ValueError("task_judgment_required")
            turns = trace["turns"]
            if not isinstance(turns, list) or not turns:
                raise ValueError("turn_metrics_required")
            observed = {k: [] for k in TIMINGS}
            for turn in turns:
                for key in TIMINGS:
                    value = turn.get(key)
                    if value is not None:
                        if type(value) not in (int, float) or not 0 <= value <= 300000:
                            raise ValueError("invalid_timing")
                        observed[key].append(value)
            for key in TIMINGS:
                timings[key].extend(observed[key])
            for key, (n, d) in validated_counts.items():
                counts[key][0] += n
                counts[key][1] += d
            completed.append(judgments["completed_task"])
            result.update(
                status="reviewed",
                gates_passed=all(gates[k] for k in GATES),
                duration_seconds=round(duration, 2),
                missing_timings=[k for k in TIMINGS if not observed[k]],
            )
        except (
            OSError,
            wave.Error,
            EOFError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ):
            result["status"] = "invalid_evidence"
        results.append(result)
    reviewed = [r for r in results if r["status"] == "reviewed"]
    return {
        "planned": len(scenarios),
        "reviewed": len(reviewed),
        "release_gates_passed": len(reviewed) == len(scenarios)
        and all(r["gates_passed"] and not r["missing_timings"] for r in reviewed),
        "metrics": {key: n / d if d else None for key, (n, d) in counts.items()},
        "task_completion": sum(completed) / len(completed) if completed else None,
        "latency_ms": {
            key: {
                "samples": len(values),
                "p50": percentile(values, 0.5),
                "p95": percentile(values, 0.95),
            }
            for key, values in timings.items()
        },
        "results": results,
    }
