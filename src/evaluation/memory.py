"""Score the same validated facts that the automatic memory worker would retain."""


def score_memory(expected, retained):
    expected_set = {tuple(sorted(fact.items())) for fact in expected}
    retained_set = {tuple(sorted(fact.items())) for fact in retained}
    return {
        "passed": expected_set == retained_set,
        "correct": len(expected_set & retained_set),
        "retained": len(retained_set),
        "expected": len(expected_set),
    }


def summarize_memory(results):
    complete = [r for r in results if r["status"] == "completed"]
    correct = sum(r["score"]["correct"] for r in complete)
    retained = sum(r["score"]["retained"] for r in complete)
    expected = sum(r["score"]["expected"] for r in complete)
    return {
        "cases": len(results),
        "completed": len(complete),
        "provider_errors": sum(r["status"] == "error" for r in results),
        "exact_case_matches": sum(r["score"]["passed"] for r in complete),
        "memory_precision": correct / retained if retained else None,
        "memory_recall": correct / expected if expected else None,
        "basis": "real-provider extraction passed through the production retention gate; text only, bilingual review pending",
    }
