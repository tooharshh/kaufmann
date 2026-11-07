import json
import logging
import time
from contextlib import contextmanager
from functools import wraps
from uuid import uuid4

from livekit.agents import llm

logger = logging.getLogger("kaufmann.voice.latency")
TIMINGS = (
    "transcription_delay",
    "end_of_turn_delay",
    "on_user_turn_completed_delay",
    "llm_node_ttft",
    "llm_node_ttfs",
    "tts_node_ttfb",
    "e2e_latency",
    "playback_latency",
)


def observe_latency(event):
    item = event.item
    if not isinstance(item, llm.ChatMessage):
        return
    timings = {
        name + "_ms": round(item.metrics[name] * 1000)
        for name in TIMINGS
        if name in item.metrics
    }
    if timings:
        logger.info(
            "voice_latency %s",
            json.dumps({"role": item.role, "message_id": item.id, **timings}),
        )


@contextmanager
def stage(name, **identifiers):
    started = time.perf_counter()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "failed"
        raise
    finally:
        logger.info(
            "voice_stage %s",
            json.dumps(
                {
                    "stage": name,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    **identifiers,
                }
            ),
        )


def timed(name):
    def decorate(function):
        @wraps(function)
        async def wrapped(self, *args, **kwargs):
            with stage(
                name,
                turn_id=str(getattr(self, "message_id", "")),
                operation_id=str(uuid4()),
            ):
                return await function(self, *args, **kwargs)

        return wrapped

    return decorate


def observe_provider(metrics):
    fields = (
        "type",
        "request_id",
        "speech_id",
        "duration",
        "ttft",
        "ttfb",
        "cancelled",
        "input_tokens",
        "output_tokens",
        "acquire_time",
        "connection_reused",
    )
    logger.info(
        "voice_provider %s",
        json.dumps(
            {name: getattr(metrics, name) for name in fields if hasattr(metrics, name)}
        ),
    )


def observe_stream(stage_name, started, **identifiers):
    logger.info(
        "voice_stream %s",
        json.dumps(
            {
                "stage": stage_name,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                **identifiers,
            }
        ),
    )
