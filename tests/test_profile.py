import asyncio
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer

from src.api import create_app
from tests.test_api import api_settings, auth_app
from tests.test_commerce_engine import ADDRESS


def test_profile_is_owned_persistent_and_address_edits_are_partial():
    async def run():
        async with (
            TestServer(auth_app({"a": uuid4(), "b": uuid4()})) as authority,
            TestClient(
                TestServer(create_app(api_settings(authority), pool=object()))
            ) as client,
        ):
            a = {"Authorization": "Bearer a"}
            b = {"Authorization": "Bearer b"}
            assert (await client.get("/profile")).status == 200
            assert (await client.get("/api/profile")).status == 401
            initial = (await (await client.get("/api/profile", headers=a)).json())[
                "profile"
            ]

            async def update(operation, data, revision):
                return await (
                    await client.post(
                        "/api/profile",
                        headers=a,
                        json={
                            "operation": operation,
                            "data": data,
                            "revision": revision,
                        },
                    )
                ).json()

            saved = await update(
                "details",
                {"name": "Shopper", "phone": "+91 9876543210"},
                initial["revision"],
            )
            assert saved["status"] == "ok"
            assert (await update("details", {"name": "stale"}, None))[
                "status"
            ] == "conflict"
            added = await update(
                "save_address",
                {"label": "Home", "patch": ADDRESS},
                saved["profile"]["revision"],
            )
            entry = added["profile"]["addresses"][0]
            edited = await update(
                "save_address",
                {"id": entry["id"], "patch": {"state": "Karnataka"}},
                added["profile"]["revision"],
            )
            assert edited["profile"]["addresses"][0]["address"] == {
                **ADDRESS,
                "state": "Karnataka",
            }
            other = (await (await client.get("/api/profile", headers=b)).json())[
                "profile"
            ]
            assert other["addresses"] == [] and other["name"] == ""
            reread = (await (await client.get("/api/profile", headers=a)).json())[
                "profile"
            ]
            assert reread == edited["profile"]
            assert (
                await update("details", {"user_id": str(uuid4())}, reread["revision"])
            )["status"] == "invalid_input"
            deleted = await update(
                "delete_address", {"id": entry["id"]}, reread["revision"]
            )
            assert deleted["profile"]["addresses"] == []
            assert deleted["profile"]["default_address_id"] is None

    asyncio.run(run())
