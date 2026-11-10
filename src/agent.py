import asyncio
import sys
from pathlib import Path

import aiohttp

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit import agents
from livekit.agents import AgentServer, cli, room_io

from src.agents.concierge import Concierge
from src.auth import SupabaseAuth
from src.catalog.embeddings import configured_embeddings
from src.catalog.search import Catalog
from src.config import Settings
from src.db.connection import create_pool
from src.engine.cart import CommerceEngine
from src.state.memory import MemoryQueue, PreferenceMemory, extract_candidates
from src.voice.access import AGENT_NAME, verify_dispatch_context
from src.voice.latency import observe_latency, observe_provider
from src.voice.navigation import BrowserBridge
from src.voice.runtime import VoiceRuntime
from src.voice.session import create_voice_session

server = AgentServer(drain_timeout=60, num_idle_processes=1)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: agents.JobContext):
    settings = Settings.load()
    try:
        dispatch = verify_dispatch_context(
            ctx.job.metadata, ctx.job.room.name, settings["VOICE_DISPATCH_SECRET"]
        )
    except ValueError:
        ctx.shutdown(reason="Voice session authorization required")
        return
    pool = create_pool(settings["DATABASE_URL"])
    await pool.open()
    try:
        await pool.wait(timeout=15)
        await ctx.connect()
        user_id = dispatch["user_id"]
        identity = "shopper:" + str(user_id)
        async with asyncio.timeout(60):
            await ctx.wait_for_participant(identity=identity)
        http = aiohttp.ClientSession()
        profile_auth = SupabaseAuth(
            http, settings["SUPABASE_URL"], settings["SUPABASE_PUBLISHABLE_KEY"]
        )
        runtime = VoiceRuntime(
            CommerceEngine(
                pool, user_id, dispatch["catalog_id"], dispatch["generation"]
            ),
            Catalog(
                pool,
                dispatch["catalog_id"],
                user_id,
                dispatch["generation"],
                embeddings=configured_embeddings(settings, http),
            ),
            profile_auth,
            dispatch["access_token"],
        )
        runtime.memory = PreferenceMemory(pool, user_id)
        runtime.memory_queue = MemoryQueue(
            runtime.memory,
            lambda text: extract_candidates(http, settings["CEREBRAS_API_KEY"], text),
        )
        session = create_voice_session(settings, runtime)
        memory_turns = set()

        def remember_completed_turn(event):
            item = event.item
            if (
                getattr(item, "role", None) == "assistant"
                and not getattr(item, "interrupted", False)
                and runtime.message_id
                and runtime.message_id not in memory_turns
            ):
                memory_turns.add(runtime.message_id)
                runtime.memory_queue.submit(
                    runtime.request, runtime.message_id, runtime.memory_revision
                )

        session.on("conversation_item_added", remember_completed_turn)

        async def watch_catalog():
            while True:
                await asyncio.sleep(2)
                result = await runtime.engine.get_state()
                if result["status"] == "catalog_changed":
                    await session.aclose()
                    ctx.shutdown(reason="Catalog changed; reconnect voice")
                    return

        catalog_watch = asyncio.create_task(watch_catalog())
        session.on("conversation_item_added", observe_latency)
        for provider in (session.llm, session.stt, session.tts):
            provider.on("metrics_collected", observe_provider)
        bridge = BrowserBridge(ctx.room, session, runtime, identity)

        def on_error(event):
            if (
                event.source in (session.stt, session.tts)
                and not event.error.recoverable
            ):
                asyncio.create_task(bridge.publish({"type": "sarvam_rate_limit"}))
            if event.source is session.llm and not event.error.recoverable:
                language = (runtime.state or {}).get("language", "en")
                text = (
                    "క్షమించండి, ప్రస్తుతం సమాధానం ఇవ్వలేకపోతున్నాను. కొద్దిసేపటి తర్వాత మళ్లీ అడగండి."
                    if language == "te"
                    else "I could not finish that response. Please check the screen for the action status."
                )
                session.say(text, add_to_chat_ctx=False)

        session.on("error", on_error)

        session.tts.prewarm()

        async def cleanup():
            catalog_watch.cancel()
            await asyncio.gather(catalog_watch, return_exceptions=True)
            await runtime.memory_queue.close()
            await bridge.close()
            await runtime.cancel_review()
            await http.close()
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
        if "http" in locals():
            await http.close()
        await pool.close()
        raise


if __name__ == "__main__":
    Settings.load()
    cli.run_app(server)
