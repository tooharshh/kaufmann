import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit import agents
from livekit.agents import AgentServer, cli, room_io

from src.agents.concierge import Concierge
from src.catalog.search import Catalog
from src.config import Settings
from src.db.connection import create_pool
from src.engine.cart import CommerceEngine
from src.voice.access import AGENT_NAME, verify_dispatch
from src.voice.latency import observe_latency, observe_provider
from src.voice.navigation import BrowserBridge
from src.voice.runtime import VoiceRuntime
from src.voice.session import create_voice_session

server = AgentServer(drain_timeout=60, num_idle_processes=1)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: agents.JobContext):
    settings = Settings.load()
    try:
        user_id = verify_dispatch(
            ctx.job.metadata, ctx.job.room.name, settings["LIVEKIT_API_SECRET"]
        )
    except ValueError:
        ctx.shutdown(reason="Voice session authorization required")
        return
    pool = create_pool(settings["DATABASE_URL"])
    await pool.open()
    try:
        await pool.wait(timeout=15)
        await ctx.connect()
        identity = "shopper:" + str(user_id)
        async with asyncio.timeout(60):
            await ctx.wait_for_participant(identity=identity)
        runtime = VoiceRuntime(CommerceEngine(pool, user_id), Catalog(pool))
        session = create_voice_session(settings, runtime)
        session.on("conversation_item_added", observe_latency)
        for provider in (session.llm, session.stt, session.tts):
            provider.on("metrics_collected", observe_provider)

        def on_error(event):
            if event.source is session.llm and not event.error.recoverable:
                language = (runtime.state or {}).get("language", "en")
                text = (
                    "క్షమించండి, ప్రస్తుతం సమాధానం ఇవ్వలేకపోతున్నాను. కొద్దిసేపటి తర్వాత మళ్లీ అడగండి."
                    if language == "te"
                    else "I cannot respond right now. Please try again shortly."
                )
                session.say(text, add_to_chat_ctx=False)

        session.on("error", on_error)

        session.tts.prewarm()
        bridge = BrowserBridge(ctx.room, session, runtime, identity)

        async def cleanup():
            await bridge.close()
            await runtime.cancel_review()
            await pool.close()

        ctx.add_shutdown_callback(cleanup)
        await session.start(
            room=ctx.room,
            agent=Concierge(runtime),
            room_options=room_io.RoomOptions(
                participant_identity=identity,
                close_on_disconnect=True,
                text_input=False,
            ),
            record=False,
        )
        await bridge.start()
        session.generate_reply(
            instructions="Greet briefly in English and ask what the shopper is looking for. Do not state product facts before a tool result."
        )
    except BaseException:
        await pool.close()
        raise


if __name__ == "__main__":
    Settings.load()
    cli.run_app(server)
