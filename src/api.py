import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import aiohttp
import psycopg
from aiohttp import web
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout

from src.auth import AuthFailure, SupabaseAuth, public_auth_config
from src.catalog.search import Catalog
from src.config import Settings
from src.db.connection import create_pool
from src.engine.cart import CommerceEngine
from src.profile import profile_view, update_profile, user_request
from src.voice.access import voice_session


@dataclass
class Services:
    pool: object
    auth: SupabaseAuth
    catalog: Catalog = field(init=False)

    def __post_init__(self):
        self.catalog = Catalog(self.pool)


SERVICES = web.AppKey("services", Services)
USER = web.RequestKey("authenticated_user_id", UUID)
HTTP_STATUSES = {
    "ok": 200,
    "not_found": 404,
    "unavailable": 503,
    "invalid_input": 400,
    "invalid_quantity": 400,
    "invalid_budget": 400,
    "invalid_address": 400,
    "invalid_token": 400,
    "amount_out_of_range": 400,
}
ACTIONS = {
    "add_item": ({"product_id", "quantity", "expected_version"}, set()),
    "set_quantity": ({"product_id", "quantity", "expected_version"}, set()),
    "remove_item": ({"product_id", "expected_version"}, set()),
    "set_budget": ({"budget_paise", "expected_version"}, set()),
    "set_address": ({"patch", "expected_version"}, set()),
    "update_context": (
        {"expected_version"},
        {"add_instruction", "remove_instruction", "language", "result_ids"},
    ),
    "resolve_reference": ({"position", "expected_version"}, set()),
    "approve_budget_exception": ({"token", "expected_version"}, set()),
}


def reply(result: dict) -> web.Response:
    response = web.json_response(
        result, status=HTTP_STATUSES.get(result["status"], 409)
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def body(
    request: web.Request, required: set, optional: set | None = None
) -> dict:
    if request.content_type != "application/json":
        raise web.HTTPBadRequest()
    try:
        data = await request.json()
    except (ValueError, UnicodeError):
        raise web.HTTPBadRequest() from None
    if (
        not isinstance(data, dict)
        or not required <= data.keys()
        or data.keys() - required - (optional or set())
    ):
        raise web.HTTPBadRequest()
    return data


def create_app(settings: Settings | None = None, *, pool=None) -> web.Application:
    settings = settings or Settings.load()
    origin = settings.values.get("APP_ORIGIN", "http://localhost:5173")
    web_root = Path(__file__).resolve().parents[1] / "web"
    public_paths = {
        "/",
        "/cart",
        "/orders",
        "/profile",
        "/assets/app.js",
        "/assets/styles.css",
        "/assets/voice.js",
        "/assets/livekit-client-2.23.0.umd.js",
        "/health",
        "/ready",
        "/api/config",
    }

    @web.middleware
    async def boundary(request, handler):
        request_origin = request.headers.get("Origin")
        same_origin = request_origin == str(request.url.origin())
        if request_origin and request_origin != origin and not same_origin:
            return web.json_response({"status": "origin_not_allowed"}, status=403)
        try:
            if request.method == "OPTIONS":
                response = web.Response(status=204)
            else:
                response = await handler(request)
        except AuthFailure as exc:
            response = web.json_response({"status": exc.status}, status=exc.http_status)
        except web.HTTPException as exc:
            response = web.json_response(
                {
                    "status": "invalid_input"
                    if exc.status == 400
                    else "request_rejected"
                },
                status=exc.status,
            )
        except (psycopg.Error, PoolTimeout, TimeoutError):
            response = web.json_response({"status": "unavailable"}, status=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: http: data:; connect-src 'self' "
            + settings["SUPABASE_URL"]
            + " "
            + settings.values.get("LIVEKIT_URL", "")
            + " "
            + settings.values.get("LIVEKIT_URL", "").replace("wss://", "https://")
            + "; worker-src 'self' blob:; media-src 'self' blob:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if request_origin and (request_origin == origin or same_origin):
            response.headers.update(
                {
                    "Access-Control-Allow-Origin": request_origin,
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Vary": "Origin",
                }
            )
        return response

    @web.middleware
    async def authenticated(request, handler):
        if request.path not in public_paths and not request.path.startswith(
            "/product/"
        ):
            request[USER] = await request.app[SERVICES].auth.authenticate(
                request.headers.get("Authorization")
            )
        return await handler(request)

    async def resources(app):
        database = pool if pool is not None else create_pool(settings["DATABASE_URL"])
        if pool is None:
            await database.open()
        try:
            async with aiohttp.ClientSession() as http:
                app[SERVICES] = Services(
                    database,
                    SupabaseAuth(
                        http,
                        settings["SUPABASE_URL"],
                        settings["SUPABASE_PUBLISHABLE_KEY"],
                    ),
                )
                yield
        finally:
            if pool is None:
                await database.close()

    async def health(request):
        return reply({"status": "ok"})

    async def index(request):
        return web.FileResponse(web_root / "index.html")

    async def asset(request):
        filename = request.match_info["filename"]
        folder = (
            web_root / "vendor"
            if filename == "livekit-client-2.23.0.umd.js"
            else web_root
        )
        return web.FileResponse(folder / filename)

    async def voice_connect(request):
        await body(request, set())
        return reply(voice_session(settings, request[USER]))

    async def config(request):
        return reply(public_auth_config(settings))

    async def ready(request):
        async with (
            asyncio.timeout(3),
            request.app[SERVICES].pool.connection(timeout=2) as connection,
        ):
            await connection.execute("select 1")
        return reply({"status": "ok"})

    async def catalog_search(request):
        if request.query.keys() - {
            "query",
            "category",
            "max_price_paise",
            "min_price_paise",
            "sort_by",
            "filters",
            "min_rating",
            "availability",
            "limit",
            "offset",
        }:
            raise web.HTTPBadRequest()
        try:
            maximum = (
                int(request.query["max_price_paise"])
                if "max_price_paise" in request.query
                else None
            )
            limit = int(request.query.get("limit", "5"))
            minimum = (
                int(request.query["min_price_paise"])
                if "min_price_paise" in request.query
                else None
            )
            import json

            filters = json.loads(request.query.get("filters", "{}"))
            minimum_rating = (
                float(request.query["min_rating"])
                if "min_rating" in request.query
                else None
            )
            offset = int(request.query.get("offset", "0"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        result = await request.app[SERVICES].catalog.search(
            request.query.get("query", ""),
            category=request.query.get("category", ""),
            max_price_paise=maximum,
            min_price_paise=minimum,
            sort_by=request.query.get("sort_by", "relevance"),
            filters=filters,
            min_rating=minimum_rating,
            availability=request.query.get("availability", "discoverable"),
            limit=limit,
            offset=offset,
        )
        return reply(result)

    async def catalog_filters(request):
        return reply(await request.app[SERVICES].catalog.filter_options())

    async def catalog_get(request):
        return reply(
            await request.app[SERVICES].catalog.get(request.match_info["product_id"])
        )

    async def catalog_compare(request):
        data = await body(request, {"product_ids"}, {"attributes"})
        return reply(
            await request.app[SERVICES].catalog.compare(
                data["product_ids"], attributes=data.get("attributes")
            )
        )

    async def session_state(request):
        return reply(
            await CommerceEngine(request.app[SERVICES].pool, request[USER]).get_state()
        )

    async def action(request):
        name = request.match_info["action"]
        if name not in ACTIONS:
            raise web.HTTPNotFound()
        required, optional = ACTIONS[name]
        data = await body(request, required, optional)
        if type(data["expected_version"]) is not int or data["expected_version"] < 0:
            raise web.HTTPBadRequest()
        engine = CommerceEngine(request.app[SERVICES].pool, request[USER])
        message_id = uuid4()
        system_context = name == "resolve_reference" or (
            name == "update_context" and set(data) == {"expected_version", "result_ids"}
        )
        if not system_context:
            registered = await engine.record_user_message(message_id)
            if registered["status"] != "ok":
                return reply(registered)
        if name == "approve_budget_exception":
            data["approval_message_id"] = message_id
        result = await getattr(engine, name)(**data)
        response = reply(result)
        response.headers["X-Request-ID"] = str(message_id)
        return response

    async def profile_get(request):
        user = await user_request(
            request.app[SERVICES].auth, request.headers["Authorization"], request[USER]
        )
        return reply({"status": "ok", "profile": profile_view(user)})

    async def profile_update(request):
        data = await body(request, {"operation", "data", "revision"})
        if (
            not isinstance(data["operation"], str)
            or not isinstance(data["data"], dict)
            or (data["revision"] is not None and not isinstance(data["revision"], str))
        ):
            raise web.HTTPBadRequest()
        return reply(
            await update_profile(
                request.app[SERVICES].auth,
                request.headers["Authorization"],
                request[USER],
                **data,
            )
        )

    async def order_list(request):
        try:
            offset = int(request.query.get("offset", "0"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        if offset < 0 or offset > 100000:
            raise web.HTTPBadRequest()
        async with (
            asyncio.timeout(8),
            request.app[SERVICES].pool.connection(timeout=3) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            await cursor.execute(
                "select id, status, snapshot, created_at from public.orders where user_id = %s order by created_at desc, id desc limit 51 offset %s",
                (request[USER], offset),
            )
            rows = await cursor.fetchall()
        return reply(
            {
                "status": "ok",
                "has_more": len(rows) > 50,
                "orders": [
                    {
                        "id": str(row["id"]),
                        "status": row["status"],
                        "snapshot": row["snapshot"],
                        "created_at": row["created_at"].isoformat(),
                    }
                    for row in rows[:50]
                ],
            }
        )

    async def order_get(request):
        try:
            order_id = UUID(request.match_info["order_id"])
        except ValueError:
            raise web.HTTPBadRequest() from None
        async with (
            asyncio.timeout(8),
            request.app[SERVICES].pool.connection(timeout=3) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            await cursor.execute(
                "select id, status, snapshot, created_at from public.orders where id = %s and user_id = %s",
                (order_id, request[USER]),
            )
            row = await cursor.fetchone()
        if row is None:
            return reply({"status": "not_found", "order": None})
        return reply(
            {
                "status": "ok",
                "order": {
                    "id": str(row["id"]),
                    "status": row["status"],
                    "snapshot": row["snapshot"],
                    "created_at": row["created_at"].isoformat(),
                },
            }
        )

    async def checkout(request):
        kind = request.match_info["kind"]
        required = {
            "prepare": {"expected_version"},
            "rendered": {"token"},
            "confirm": {"token", "expected_version"},
            "cancel": {"token"},
        }
        if kind not in required:
            raise web.HTTPNotFound()
        data = await body(request, required[kind])
        engine = CommerceEngine(request.app[SERVICES].pool, request[USER])
        if kind == "rendered":
            return reply(await engine.record_review_delivery(data["token"], uuid4()))
        if kind == "cancel":
            return reply(await engine.interrupt_review(data["token"]))
        if type(data["expected_version"]) is not int or data["expected_version"] < 0:
            raise web.HTTPBadRequest()
        message_id = uuid4()
        registered = await engine.record_user_message(message_id)
        if registered["status"] != "ok":
            return reply(registered)
        if kind == "prepare":
            return reply(await engine.prepare_order(data["expected_version"]))
        return reply(
            await engine.confirm_order(
                data["token"], data["expected_version"], message_id
            )
        )

    app = web.Application(middlewares=[boundary, authenticated], client_max_size=16384)
    app.cleanup_ctx.append(resources)
    app.add_routes(
        [
            web.get("/", index),
            web.get("/cart", index),
            web.get("/orders", index),
            web.get("/profile", index),
            web.get("/product/{page_product_id:[^/]{1,128}}", index),
            web.get(
                "/assets/{filename:app\\.js|voice\\.js|styles\\.css|livekit-client-2\\.23\\.0\\.umd\\.js}",
                asset,
            ),
            web.get("/api/config", config),
            web.get("/health", health),
            web.get("/ready", ready),
            web.get("/api/catalog/search", catalog_search),
            web.post("/api/catalog/compare", catalog_compare),
            web.get("/api/catalog/filters", catalog_filters),
            web.get("/api/catalog/{product_id}", catalog_get),
            web.get("/api/session", session_state),
            web.post("/api/voice/session", voice_connect),
            web.post("/api/actions/{action}", action),
            web.get("/api/profile", profile_get),
            web.post("/api/profile", profile_update),
            web.get("/api/orders", order_list),
            web.get("/api/orders/{order_id}", order_get),
            web.post("/api/checkout/{kind}", checkout),
        ]
    )
    return app


if __name__ == "__main__":
    application = create_app()
    web.run_app(
        application,
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        access_log=None,
    )
