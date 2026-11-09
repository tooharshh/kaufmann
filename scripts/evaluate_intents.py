"""Bounded opt-in model intent evaluation. Never writes commerce state."""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit.agents import APIError

from src.agents.cart import CartAgent
from src.agents.checkout import CheckoutAgent
from src.agents.shopping_advisor import ShoppingAdvisor
from src.config import Settings
from src.evaluation.intents import load_cases, run_case, summarize
from src.voice.runtime import VoiceRuntime
from src.voice.session import CEREBRAS_MODEL, create_voice_session


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=Path("data/evaluation/intents.jsonl")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Authorize bounded calls to the configured Cerebras model",
    )
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--delay", type=float, default=12)
    parser.add_argument("--language", choices=["en", "te", "te-Latn", "mixed"])
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="Evaluate selected behavior groups; may be repeated",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 80 or not 0 <= args.delay <= 60:
        parser.error("limit must be 1..80; delay must be 0..60 seconds")
    cases = [
        c
        for c in load_cases(args.cases)
        if (args.language is None or c["language"] == args.language)
        and (not args.group or c["group"] in args.group)
    ][: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    metadata = {
        "model": CEREBRAS_MODEL,
        "scenario_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "prompt_sha256": {
            phase: hashlib.sha256(cls(None).instructions.encode()).hexdigest()
            for phase, cls in {
                "discover": ShoppingAdvisor,
                "basket": CartAgent,
                "checkout": CheckoutAgent,
            }.items()
        },
        "started_at_utc": datetime.now(UTC).isoformat(),
        "delay_seconds": args.delay,
        "max_steps_per_case": 6,
        "live": args.live,
    }
    session = (
        create_voice_session(Settings.load(), VoiceRuntime(None, None))
        if args.live
        else None
    )
    try:
        for index, case in enumerate(cases):
            if session:
                if index:
                    await asyncio.sleep(args.delay)
                try:
                    async with asyncio.timeout(60):
                        result = await run_case(session.llm, case)
                except (
                    APIError,
                    TimeoutError,
                    ValueError,
                    TypeError,
                    KeyError,
                ) as exc:  # Deliberately isolate provider failures; never print provider bodies or credentials.
                    result = {
                        "id": case["id"],
                        "language": case["language"],
                        "status": "error",
                        "error_type": type(exc).__name__,
                    }
            else:
                result = {
                    "id": case["id"],
                    "language": case["language"],
                    "status": "not_run",
                }
            results.append(result)
            args.output.write_text(
                json.dumps(
                    {
                        "metadata": metadata,
                        "summary": summarize(results),
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
    finally:
        if session:
            await session.llm.aclose()
            await session.stt.aclose()
            await session.tts.aclose()


if __name__ == "__main__":
    asyncio.run(main())
