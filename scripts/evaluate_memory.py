"""Bounded opt-in selective memory extraction evaluation; no user data is written."""

import argparse
import asyncio
import hashlib
import inspect
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from src.config import Settings
from src.evaluation.memory import score_memory, summarize_memory
from src.state.memory import (
    MemoryExtractionUnavailable,
    extract_candidates,
    validated_candidates,
)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=Path("data/evaluation/memory.jsonl")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20 or not 0 <= args.delay <= 60:
        parser.error("limit must be 1..20; delay must be 0..60 seconds")
    cases = [
        json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()
    ][: args.limit]
    settings = Settings.load() if args.live else None
    metadata = {
        "model": "gpt-oss-120b",
        "scenario_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "extractor_sha256": hashlib.sha256(
            inspect.getsource(extract_candidates).encode()
        ).hexdigest(),
        "language_aids_sha256": hashlib.sha256(
            Path("src/language/requests.py").read_bytes()
        ).hexdigest(),
        "live": args.live,
        "delay_seconds": args.delay,
    }
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as http:
        for index, case in enumerate(cases):
            result = {
                "id": case["id"],
                "language": case["language"],
                "status": "not_run",
                "human_review": case["human_review"],
            }
            if settings:
                if index:
                    await asyncio.sleep(args.delay)
                try:
                    candidates = await extract_candidates(
                        http, settings["CEREBRAS_API_KEY"], case["input"]
                    )
                    retained = validated_candidates(case["input"], candidates)
                    result.update(
                        status="completed",
                        retained_facts=retained,
                        score=score_memory(case["expected_facts"], retained),
                    )
                except (
                    MemoryExtractionUnavailable,
                    aiohttp.ClientError,
                    TimeoutError,
                    ValueError,
                    KeyError,
                    TypeError,
                ) as exc:
                    result.update(status="error", error_type=type(exc).__name__)
            results.append(result)
            args.output.write_text(
                json.dumps(
                    {
                        "metadata": metadata,
                        "summary": summarize_memory(results),
                        "results": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            print(
                json.dumps(
                    {
                        "id": case["id"],
                        "status": result["status"],
                        "passed": result.get("score", {}).get("passed"),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
