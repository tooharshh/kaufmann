from livekit.agents import (
    AgentSession,
    APIConnectOptions,
    SessionConnectOptions,
    TurnHandlingOptions,
)
from livekit.plugins import openai, sarvam

from src.voice.phrases import StreamingSarvamTTS

CEREBRAS_MODEL = "gpt-oss-120b"


def create_voice_session(settings, runtime):
    return AgentSession(
        userdata=runtime,
        conn_options=SessionConnectOptions(
            llm_conn_options=APIConnectOptions(max_retry=0, timeout=8.0),
        ),
        llm=openai.LLM(
            model=CEREBRAS_MODEL,
            base_url="https://api.cerebras.ai/v1",
            api_key=settings["CEREBRAS_API_KEY"],
            temperature=0.2,
            parallel_tool_calls=False,
            max_completion_tokens=768,
            reasoning_effort="low",
            max_retries=0,
            _strict_tool_schema=False,
        ),
        stt=sarvam.STT(
            api_key=settings["SARVAM_API_KEY"],
            language="unknown",
            flush_signal=True,
        ),
        tts=StreamingSarvamTTS(
            protected=runtime.protected_speech,
            api_key=settings["SARVAM_API_KEY"],
            target_language_code="en-IN",
            min_buffer_size=30,
            max_chunk_length=80,
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={"min_delay": 0.2, "max_delay": 3.0},
            interruption={
                "enabled": True,
                "mode": "vad",
                "min_duration": 0.15,
                "min_words": 0,
                "resume_false_interruption": False,
            },
            preemptive_generation={"enabled": False},
        ),
        max_tool_steps=6,
    )
