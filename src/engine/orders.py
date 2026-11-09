import secrets
from uuid import uuid4

from psycopg.types.json import Jsonb

from src.engine.pricing import budget_digest, quote
from src.state.persistence import save_session
from src.state.session import Refusal, require_address, token_hash, valid_uuid


class CheckoutMixin:
    async def prepare_order(self, expected_version):
        async def prepare(connection, session):
            if not session["latest_message_id"]:
                raise Refusal("user_turn_required")
            if session["pending_address"]:
                raise Refusal("address_approval_required")
            items = await self._items(connection, session)
            if not items:
                raise Refusal("empty_cart")
            require_address(session["address"])
            snapshot = quote(items)
            budget = session["budget_paise"]
            if (
                budget is not None
                and snapshot["total_paise"] > budget
                and session["budget_authorization"] != budget_digest(snapshot, budget)
            ):
                return await self._budget_proposal(
                    connection, session, snapshot, kind="checkout"
                )
            snapshot["catalog_id"] = str(session["catalog_id"])
            snapshot["address"] = session["address"]
            snapshot["version"] = session["version"]
            token = secrets.token_urlsafe(32)
            await save_session(
                connection,
                session,
                {
                    "pending_review": {
                        "snapshot": snapshot,
                        "turn_seq": session["turn_seq"],
                    },
                    "pending_token_hash": token_hash(token),
                    "review_delivery_id": None,
                    "pending_budget": None,
                },
            )
            return {"status": "ok", "pending_token": token, "read_back": snapshot}

        return await self._run(prepare, expected=expected_version, mutation=True)

    async def record_review_delivery(self, token, delivery_id):
        async def delivered(connection, session):
            pending = session["pending_review"]
            if not pending or token_hash(token) != session["pending_token_hash"]:
                raise Refusal("stale_token")
            if session["turn_seq"] != pending["turn_seq"]:
                raise Refusal("review_interrupted")
            await save_session(
                connection, session, {"review_delivery_id": valid_uuid(delivery_id)}
            )
            return {"status": "ok"}

        return await self._run(delivered)

    async def interrupt_review(self, token):
        async def interrupted(connection, session):
            if session["pending_token_hash"] != token_hash(token):
                raise Refusal("stale_token")
            await save_session(
                connection,
                session,
                {
                    "pending_review": None,
                    "pending_token_hash": None,
                    "review_delivery_id": None,
                },
            )
            return {"status": "ok"}

        return await self._run(interrupted)

    async def confirm_order(self, token, expected_version, approval_message_id):
        async def confirm(connection, session):
            confirmation_hash = token_hash(token)
            cursor = await connection.execute(
                "select id, total_paise, address, status from public.orders where confirmation_hash = %s and user_id = %s",
                (confirmation_hash, self.user_id),
            )
            existing = await cursor.fetchone()
            if existing:
                return {
                    "status": "ok",
                    "order": {**existing, "id": str(existing["id"])},
                    "already_confirmed": True,
                }
            self._version(session, expected_version)
            pending = session["pending_review"]
            if not pending or confirmation_hash != session["pending_token_hash"]:
                raise Refusal("stale_token")
            if not session["review_delivery_id"]:
                raise Refusal("review_not_delivered")
            self._later_approval(session, approval_message_id, pending["turn_seq"])
            ids = [item["product_id"] for item in pending["snapshot"]["items"]]
            await connection.execute(
                "select uniq_id from public.products where uniq_id = any(%s) order by uniq_id for share",
                (ids,),
            )
            await connection.execute(
                "select product_id from public.demo_inventory where product_id = any(%s) order by product_id for update",
                (ids,),
            )
            snapshot = quote(await self._items(connection, session))
            require_address(session["address"])
            snapshot["catalog_id"] = str(session["catalog_id"])
            snapshot["address"] = session["address"]
            snapshot["version"] = session["version"]
            if snapshot != pending["snapshot"]:
                await save_session(
                    connection,
                    session,
                    {
                        "pending_review": None,
                        "pending_token_hash": None,
                        "review_delivery_id": None,
                    },
                )
                return {"status": "price_changed"}
            order_id = uuid4()
            await connection.execute(
                "insert into public.orders (id, user_id, session_id, confirmation_hash, total_paise, address, snapshot, catalog_id) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    order_id,
                    self.user_id,
                    session["id"],
                    confirmation_hash,
                    snapshot["total_paise"],
                    Jsonb(snapshot["address"]),
                    Jsonb(snapshot),
                    session["catalog_id"],
                ),
            )
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "insert into public.order_items (order_id, product_id, product_name, quantity, unit_price_paise, line_total_paise) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    [
                        (
                            order_id,
                            item["product_id"],
                            item["name"],
                            item["quantity"],
                            item["unit_price_paise"],
                            item["line_total_paise"],
                        )
                        for item in snapshot["items"]
                    ],
                )
            for item in snapshot["items"]:
                await connection.execute(
                    "update public.demo_inventory set available = available - %s where product_id = %s",
                    (item["quantity"], item["product_id"]),
                )
            await connection.execute(
                "delete from public.cart_items where session_id = %s", (session["id"],)
            )
            await save_session(connection, session, {}, bump=True, invalidate=True)
            return {
                "status": "ok",
                "order": {
                    "id": str(order_id),
                    "total_paise": snapshot["total_paise"],
                    "address": snapshot["address"],
                    "status": "demo_confirmed",
                },
                "already_confirmed": False,
            }

        return await self._run(confirm)
