import asyncio
import os
from uuid import uuid4

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer
from psycopg_pool import PoolTimeout

from src.api import create_app
from src.auth import AuthFailure, SupabaseAuth, public_auth_config
from src.config import Settings
from tests.test_commerce_engine import ADDRESS, shop


def auth_app(users):
    metadata = {}

    async def user(request):
        assert request.headers["apikey"] == "sb_publishable_test-key"
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token == "offline":
            return web.json_response({"private": "details"}, status=503)
        if token == "anonymous":
            return web.json_response({"id": str(uuid4()), "is_anonymous": True})
        if token not in users:
            return web.json_response({"private": "details"}, status=401)
        saved = metadata.setdefault(str(users[token]), {})
        if request.method == "PUT":
            payload = await request.json()
            assert set(payload) == {"data"}
            saved.update(payload["data"])
        return web.json_response(
            {
                "id": str(users[token]),
                "email": "qa@example.test",
                "user_metadata": saved,
                "is_anonymous": False,
            }
        )

    app = web.Application()
    app.router.add_get("/auth/v1/user", user)
    app.router.add_put("/auth/v1/user", user)
    return app


def api_settings(server):
    return Settings(
        {
            "SUPABASE_URL": str(server.make_url("/")).rstrip("/"),
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test-key",
            "APP_ORIGIN": "http://localhost:5173",
            "LIVEKIT_URL": "wss://example.livekit.cloud",
            "LIVEKIT_API_KEY": "local-test-key",
            "LIVEKIT_API_SECRET": "local-test-secret-with-at-least-32-bytes",
            "VOICE_DISPATCH_SECRET": "different-shared-dispatch-secret-32-bytes",
        }
    )


def test_auth_validates_with_server_and_rejects_missing_invalid_anonymous_tokens():
    with pytest.raises(AuthFailure):
        public_auth_config(
            Settings({"SUPABASE_PUBLISHABLE_KEY": "sb_secret_do-not-expose"})
        )

    async def run():
        user_id = uuid4()
        async with (
            TestServer(auth_app({"valid": user_id})) as server,
            ClientSession() as http,
        ):
            auth = SupabaseAuth(
                http, str(server.make_url("/")), "sb_publishable_test-key"
            )
            assert await auth.authenticate("Bearer valid") == user_id
            for header, status in (
                (None, "unauthorized"),
                ("Bearer invalid", "unauthorized"),
                ("Bearer anonymous", "sign_in_required"),
                ("Bearer offline", "auth_unavailable"),
            ):
                with pytest.raises(AuthFailure) as caught:
                    await auth.authenticate(header)
                assert caught.value.status == status

    asyncio.run(run())


def test_http_boundaries_fail_closed_without_exposing_details():
    class OfflinePool:
        def connection(self, **kwargs):
            raise PoolTimeout("private database details")

    async def run():
        async with (
            TestServer(auth_app({"valid": uuid4()})) as server,
            TestClient(
                TestServer(create_app(api_settings(server), pool=OfflinePool()))
            ) as client,
        ):
            assert (await client.get("/")).status == 200
            assert (await client.get("/cart")).status == 200
            assert (await client.get("/orders")).status == 200
            assert (await client.get("/product/test-item")).status == 200
            assert (await client.get("/assets/app.js")).status == 200
            assert (await client.get("/assets/voice.js")).status == 200
            assert (
                await client.get("/assets/livekit-client-2.23.0.umd.js")
            ).status == 200
            assert (await client.post("/api/voice/session", json={})).status == 401
            voice = await client.post(
                "/api/voice/session", headers={"Authorization": "Bearer valid"}, json={}
            )
            assert voice.status == 503
            assert await voice.json() == {"status": "unavailable"}
            assert (
                await client.post(
                    "/api/voice/session",
                    headers={"Authorization": "Bearer valid"},
                    json={"user_id": str(uuid4())},
                )
            ).status == 400
            config = await (await client.get("/api/config")).json()
            assert set(config) == {"status", "supabase_url", "publishable_key"}
            assert (await client.get("/health")).status == 200
            assert (await client.get("/ready")).status == 503
            assert (await client.get("/api/session")).status == 401
            headers = {"Authorization": "Bearer valid"}
            for private_path in (
                "/.env",
                "/AGENTS.md",
                "/src/agent.py",
                "/assets/../src/agent.py",
            ):
                response = await client.get(private_path, headers=headers)
                assert response.status == 404
            response = await client.post(
                "/api/actions/add_item",
                headers=headers,
                json={
                    "product_id": "p",
                    "quantity": 1,
                    "expected_version": 0,
                    "user_id": str(uuid4()),
                },
            )
            assert response.status == 400
            response = await client.post(
                "/api/actions/set_budget",
                headers={**headers, "Content-Type": "application/json"},
                data="{",
            )
            assert response.status == 400
            assert (
                await client.post(
                    "/api/actions/record_review_delivery", headers=headers, json={}
                )
            ).status == 404
            assert (
                await client.post(
                    "/api/actions/confirm_order", headers=headers, json={}
                )
            ).status == 404
            assert (
                await client.get("/api/catalog/search?limit=bad", headers=headers)
            ).status == 400
            response = await client.get(
                "/api/session", headers={"Authorization": "Bearer offline"}
            )
            assert response.status == 503
            assert await response.json() == {"status": "auth_unavailable"}
            response = await client.options(
                "/api/session", headers={"Origin": "http://localhost:5173"}
            )
            assert response.status == 204
            assert (
                response.headers["Access-Control-Allow-Origin"]
                == "http://localhost:5173"
            )
            response = await client.get(
                "/api/session",
                headers={**headers, "Origin": "https://untrusted.example"},
            )
            assert response.status == 403
            assert "Access-Control-Allow-Origin" not in response.headers

    asyncio.run(run())


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL"
)
def test_authenticated_http_cart_uses_engine_versions_and_owner_scoped_reads():
    async def run():
        async with (
            shop() as (pool, _engines, products, users),
            TestServer(auth_app({"user-a": users[0], "user-b": users[1]})) as server,
            TestClient(
                TestServer(create_app(api_settings(server), pool=pool))
            ) as client,
        ):
            a = {"Authorization": "Bearer user-a"}
            b = {"Authorization": "Bearer user-b"}
            state = await (await client.get("/api/session", headers=a)).json()
            assert state["state"]["items"] == []
            response = await client.post(
                "/api/actions/add_item",
                headers=a,
                json={
                    "product_id": products[0],
                    "quantity": 1,
                    "expected_version": state["state"]["version"],
                },
            )
            added = await response.json()
            assert response.status == 200
            assert added["state"]["total_paise"] == 10000
            assert (
                await client.post(
                    "/api/actions/add_item",
                    headers=a,
                    json={
                        "product_id": products[0],
                        "quantity": 1,
                        "expected_version": state["state"]["version"],
                    },
                )
            ).status == 409
            response = await client.get(
                "/api/catalog/search?query=shirt&max_price_paise=10000", headers=a
            )
            assert response.status == 200
            assert {p["id"] for p in (await response.json())["products"]} == set(
                products
            )
            response = await client.post(
                "/api/actions/set_budget",
                headers=a,
                json={
                    "budget_paise": 4000,
                    "expected_version": added["state"]["version"],
                },
            )
            budget = await response.json()
            response = await client.post(
                "/api/actions/add_item",
                headers=a,
                json={
                    "product_id": products[1],
                    "quantity": 1,
                    "expected_version": budget["state"]["version"],
                },
            )
            proposal = await response.json()
            assert response.status == 409
            assert proposal["status"] == "over_budget"
            response = await client.post(
                "/api/actions/approve_budget_exception",
                headers=a,
                json={
                    "token": proposal["exception_token"],
                    "expected_version": proposal["state"]["version"],
                },
            )
            accepted = await response.json()
            assert response.status == 200
            assert accepted["state"]["total_paise"] == 16000
            assert accepted["state"]["budget_paise"] == 4000
            other = await (await client.get("/api/session", headers=b)).json()
            assert other["state"]["items"] == []
            added_b = await (
                await client.post(
                    "/api/actions/add_item",
                    headers=b,
                    json={
                        "product_id": products[1],
                        "quantity": 1,
                        "expected_version": other["state"]["version"],
                    },
                )
            ).json()
            address_b = await (
                await client.post(
                    "/api/actions/set_address",
                    headers=b,
                    json={
                        "patch": ADDRESS,
                        "expected_version": added_b["state"]["version"],
                    },
                )
            ).json()
            version_b = address_b["state"]["version"]
            first = await (
                await client.post(
                    "/api/checkout/prepare",
                    headers=b,
                    json={"expected_version": version_b},
                )
            ).json()
            assert first["status"] == "ok"
            assert (
                await client.post(
                    "/api/checkout/rendered",
                    headers=b,
                    json={"token": first["pending_token"], "delivered": True},
                )
            ).status == 400
            premature = await client.post(
                "/api/checkout/confirm",
                headers=b,
                json={"token": first["pending_token"], "expected_version": version_b},
            )
            assert premature.status == 409
            prepared = await (
                await client.post(
                    "/api/checkout/prepare",
                    headers=b,
                    json={"expected_version": version_b},
                )
            ).json()
            rendered = await client.post(
                "/api/checkout/rendered",
                headers=b,
                json={"token": prepared["pending_token"]},
            )
            assert rendered.status == 200
            cancelled = await client.post(
                "/api/checkout/cancel",
                headers=b,
                json={"token": prepared["pending_token"]},
            )
            assert cancelled.status == 200
            assert (
                await client.post(
                    "/api/checkout/confirm",
                    headers=b,
                    json={
                        "token": prepared["pending_token"],
                        "expected_version": version_b,
                    },
                )
            ).status == 409
            prepared = await (
                await client.post(
                    "/api/checkout/prepare",
                    headers=b,
                    json={"expected_version": version_b},
                )
            ).json()
            assert (
                await client.post(
                    "/api/checkout/rendered",
                    headers=b,
                    json={"token": prepared["pending_token"]},
                )
            ).status == 200
            confirmed_response = await client.post(
                "/api/checkout/confirm",
                headers=b,
                json={
                    "token": prepared["pending_token"],
                    "expected_version": version_b,
                },
            )
            assert confirmed_response.status == 200
            confirmed = await confirmed_response.json()
            retry = await (
                await client.post(
                    "/api/checkout/confirm",
                    headers=b,
                    json={
                        "token": prepared["pending_token"],
                        "expected_version": version_b,
                    },
                )
            ).json()
            assert retry["order"]["id"] == confirmed["order"]["id"]
            order_path = "/api/orders/" + confirmed["order"]["id"]
            assert (await client.get(order_path, headers=a)).status == 404
            response = await client.get(order_path, headers=b)
            assert response.status == 200
            assert (await response.json())["order"]["snapshot"]["total_paise"] == 6000
            history = await (await client.get("/api/orders", headers=b)).json()
            assert [order["id"] for order in history["orders"]] == [
                confirmed["order"]["id"]
            ]
            assert history["orders"][0]["snapshot"]["total_paise"] == 6000
            assert history["has_more"] is False
            assert (await (await client.get("/api/orders", headers=a)).json())[
                "orders"
            ] == []
            assert (await client.get("/api/orders")).status == 401
            assert (await client.get("/api/orders?offset=-1", headers=b)).status == 400
            assert (
                await (await client.get("/api/orders?offset=50", headers=b)).json()
            )["orders"] == []

    asyncio.run(run())
