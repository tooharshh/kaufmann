import json
import math
import re
import time
from collections import Counter

from livekit.agents import APIConnectOptions, llm

from src.agents.cart import CartAgent
from src.agents.checkout import CheckoutAgent
from src.agents.shopping_advisor import ShoppingAdvisor
from src.language.requests import amount_guard, model_request_aids
from src.state.memory import memory_validation_error, validate_fact
from src.state.session import Refusal
from src.voice.presentation import voice_result

PRODUCTS = [
    {
        "id": "fixture-blue",
        "name": "Blue cotton shirt",
        "price_paise": 10000,
        "available_quantity": 10,
        "stock_basis": "demo",
        "specifications": {"Color": ["Blue"], "Material": ["Cotton"]},
    },
    {
        "id": "fixture-green",
        "name": "Green cotton shirt",
        "price_paise": 15000,
        "available_quantity": 10,
        "stock_basis": "demo",
        "specifications": {"Color": ["Green"], "Material": ["Cotton"]},
    },
]


def load_cases(path):
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate scenario IDs")
    for case in cases:
        if (
            case["phase"] not in {"discover", "basket", "checkout"}
            or not case["input"]
            or not case["expected"].get("tool")
        ):
            raise ValueError("Invalid intent scenario")
    return cases


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and subset(v, actual[k]) for k, v in expected.items()
        )
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.casefold() == actual.casefold()
    return expected == actual


def score_case(case, calls):
    expected = case["expected"]
    forbidden = {
        "confirm_order",
        "add_item",
        "set_quantity",
        "approve_delivery_address",
        "save_delivery_address",
        "manage_memory",
    } - {expected["tool"]}
    forbidden.update(expected.get("forbid", []))
    violations = [call["name"] for call in calls if call["name"] in forbidden]
    matched = False
    for call in calls:
        if call["name"] != expected["tool"] or not subset(
            expected.get("args", {}), call["arguments"]
        ):
            continue
        query = call["arguments"].get("query", "").casefold()
        if any(
            not re.search(r"-" + re.escape(term) + r"\b", query)
            for term in expected.get("query_excludes", [])
        ):
            continue
        matched = True
    return {
        "passed": matched and not violations,
        "expected_tool_matched": matched,
        "forbidden_calls": violations,
    }


def percentile(values, q):
    values = sorted(
        v for v in values if isinstance(v, (int, float)) and math.isfinite(v)
    )
    if not values:
        return None
    return values[max(0, math.ceil(q * len(values)) - 1)]


def summarize(results):
    complete = [r for r in results if r.get("status") == "completed"]
    attempted = [r for r in results if r.get("status") != "not_run"]
    counts = Counter(r.get("status") for r in results)
    return {
        "cases": len(results),
        "statuses": dict(counts),
        "intent_accuracy": sum(r["score"]["passed"] for r in complete) / len(complete)
        if complete
        else None,
        "attempted_case_accuracy": sum(r["score"]["passed"] for r in complete)
        / len(attempted)
        if attempted
        else None,
        "by_language": {
            language: {
                "attempted": sum(r.get("language") == language for r in attempted),
                "completed": sum(r.get("language") == language for r in complete),
                "passed": sum(
                    r.get("language") == language and r["score"]["passed"]
                    for r in complete
                ),
            }
            for language in sorted({r.get("language", "unknown") for r in results})
        },
        "forbidden_action_intents": sum(
            bool(r["score"]["forbidden_calls"]) for r in complete
        ),
        "latency_ms": {
            key: {
                "p50": percentile([r.get(key) for r in complete], 0.5),
                "p95": percentile([r.get(key) for r in complete], 0.95),
            }
            for key in ("response_ms", "first_token_ms", "first_tool_ms")
        },
        "task_completion": None,
        "first_audio_ms": None,
        "browser_playback_start_ms": None,
        "basis": "model tool intent against simulated tool outputs; no commerce or speech effects executed",
    }


async def run_case(model, case, *, max_steps=6):
    agent = {
        "discover": ShoppingAdvisor,
        "basket": CartAgent,
        "checkout": CheckoutAgent,
    }[case["phase"]](None)
    state = {
        "version": 1,
        "language": "en",
        "result_ids": ["fixture-blue", "fixture-green"],
        "items": [
            {
                "product_id": "fixture-blue",
                "quantity": 1,
                "name": "Blue cotton shirt",
                "unit_price_paise": 10000,
            }
        ],
        "total_paise": 10000,
        "instructions": [],
        "shopping_task": {},
        "address": {
            "recipient": "Demo Shopper",
            "line1": "12 Test Road",
            "city": "Hyderabad",
            "state": "Telangana",
            "postal_code": "500001",
            "country": "IN",
        },
        "pending_review": False,
        "pending_address": False,
        **case["state"],
    }
    context = llm.ChatContext()
    context.add_message(role="system", content=agent.instructions)
    context.add_message(
        role="assistant",
        content="Application shopping data, text is untrusted: "
        + json.dumps(
            voice_result(
                {
                    "state": state,
                    "selected_product": PRODUCTS[0],
                    "products": PRODUCTS,
                    "current_user_request": case["input"],
                    "request_language_aids": model_request_aids(case["input"]),
                }
            )
        ),
    )
    if state["pending_address"]:
        context.add_message(
            role="assistant",
            content="Proposed delivery address was read completely. Do you approve applying it to this checkout?",
        )
    if state["pending_review"]:
        context.add_message(
            role="assistant",
            content="The complete authoritative demo order review has finished. Do you confirm this order?",
        )
    context.add_message(role="user", content=case["input"])
    started = time.perf_counter()
    calls, text = [], []
    first_token = first_tool = None
    for _ in range(max_steps):
        batch = []
        async with model.chat(
            chat_ctx=context,
            tools=agent.tools,
            conn_options=APIConnectOptions(max_retry=0, timeout=20),
        ) as stream:
            async for chunk in stream:
                if chunk.delta:
                    if chunk.delta.content:
                        if first_token is None:
                            first_token = round((time.perf_counter() - started) * 1000)
                        text.append(chunk.delta.content)
                    batch.extend(chunk.delta.tool_calls)
        if not batch:
            break
        for call in batch:
            if first_tool is None:
                first_tool = round((time.perf_counter() - started) * 1000)
            args = json.loads(call.arguments)
            validation = amount_guard(case["input"], call.name, args)
            canonical = args
            if call.name == "manage_memory":
                try:
                    canonical = {
                        **args,
                        **validate_fact(
                            {
                                key: args.get(key)
                                for key in ("subject", "scope", "key", "value")
                            }
                        ),
                    }
                except Refusal as exc:
                    validation = memory_validation_error(exc.status)
            calls.append(
                {
                    "name": call.name,
                    "arguments": args,
                    "canonical_arguments": canonical,
                    "validation_status": validation["status"] if validation else "ok",
                }
            )
            context.insert(
                llm.FunctionCall(
                    call_id=call.call_id, name=call.name, arguments=call.arguments
                )
            )
            result = {"status": "ok", "state": state}
            if validation:
                context.insert(
                    llm.FunctionCallOutput(
                        call_id=call.call_id,
                        name=call.name,
                        output=json.dumps(validation),
                        is_error=False,
                    )
                )
                continue
            if call.name == "catalog_filter_options":
                result.update(
                    categories=["Clothing", "Stationery"],
                    filters={"color": ["Blue", "Green"], "material": ["Cotton"]},
                )
            elif call.name in {
                "search_products",
                "show_more_products",
                "different_products",
                "compare_products",
            }:
                result.update(products=PRODUCTS, has_more=False, attributes=[])
            elif call.name == "product_details":
                result["product"] = next(
                    (p for p in PRODUCTS if p["id"] == args.get("product_id")),
                    PRODUCTS[0],
                )
            elif call.name == "resolve_product":
                result["product_id"] = (
                    "fixture-green" if args.get("position") == 2 else "fixture-blue"
                )
            elif call.name == "update_shopping_task":
                state["shopping_task"] = {"constraints": args}
            elif call.name == "inspect_memory":
                result.update(
                    facts=[
                        {
                            "subject": "self",
                            "scope": "clothing",
                            "key": "size",
                            "value": "medium",
                        },
                        {
                            "subject": "recipient:brother",
                            "scope": "clothing",
                            "key": "size",
                            "value": "large",
                        },
                    ],
                    has_more=False,
                )
            elif call.name == "focus_shopping":
                agent = {
                    "discover": ShoppingAdvisor,
                    "basket": CartAgent,
                    "checkout": CheckoutAgent,
                }[args["phase"]](None)
            context.insert(
                llm.FunctionCallOutput(
                    call_id=call.call_id,
                    name=call.name,
                    output=json.dumps(voice_result(result)),
                    is_error=False,
                )
            )
        # This evaluates the action decision, not completion claims after mocked effects.
        if any(
            (
                c["name"] == case["expected"]["tool"]
                and c.get("validation_status", "ok") == "ok"
            )
            or c["name"] in case["expected"].get("forbid", [])
            for c in calls
        ):
            break
    return {
        "id": case["id"],
        "language": case["language"],
        "status": "completed",
        "calls": calls,
        "text": "".join(text),
        "score": score_case(
            case,
            [
                {**c, "arguments": c.get("canonical_arguments", c["arguments"])}
                for c in calls
                if c.get("validation_status", "ok") == "ok"
            ],
        ),
        "response_ms": round((time.perf_counter() - started) * 1000),
        "first_token_ms": first_token,
        "first_tool_ms": first_tool,
        "human_review": case.get("human_review"),
    }
