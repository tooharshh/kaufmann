import asyncio
import secrets
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout

from src.engine.orders import CheckoutMixin
from src.engine.pricing import budget_digest, cart_item, quote
from src.state.persistence import load_session, save_session
from src.state.session import Refusal, address_patch, token_hash, valid_uuid


class CommerceEngine(CheckoutMixin):
    def __init__(self, pool, authenticated_user_id: UUID):
        self.pool = pool
        self.user_id = valid_uuid(authenticated_user_id)

    @staticmethod
    def _version(session, expected):
        if type(expected) is not int or expected < 0:
            raise Refusal("invalid_input")
        if session["version"] != expected:
            raise Refusal("conflict")

    async def _run(self, handler, *, expected=None, mutation=False, **arguments):
        try:
            async with (
                asyncio.timeout(20),
                self.pool.connection(timeout=5) as connection,
                connection.transaction(),
            ):
                connection.row_factory = dict_row
                await connection.execute("set local statement_timeout = '10s'")
                session = await load_session(connection, self.user_id)
                try:
                    if mutation:
                        self._version(session, expected)
                    result = await handler(connection, session, **arguments)
                except Refusal as exc:
                    result = {"status": exc.status}
                result["state"] = await self._view(connection, session)
                return result
        except (psycopg.Error, PoolTimeout, TimeoutError):
            return {"status": "unavailable"}

    async def _items(self, connection, session):
        cursor = await connection.execute(
            "select c.product_id, c.quantity, p.product_name, p.discounted_price, i.available "
            "from public.cart_items c join public.products p on p.uniq_id = c.product_id "
            "left join public.demo_inventory i on i.product_id = c.product_id "
            "where c.session_id = %s order by c.product_id",
            (session["id"],),
        )
        return [cart_item(row) for row in await cursor.fetchall()]

    async def _view(self, connection, session):
        items = await self._items(connection, session)
        total = (
            sum(item["line_total_paise"] for item in items)
            if all(item["line_total_paise"] is not None for item in items)
            else None
        )
        cursor = await connection.execute(
            "select id from public.orders where user_id = %s order by created_at desc, id desc limit 1",
            (self.user_id,),
        )
        last_order = await cursor.fetchone()
        return {
            "session_id": str(session["id"]),
            "version": session["version"],
            "budget_paise": session["budget_paise"],
            "address": session["address"],
            "instructions": session["instructions"],
            "language": session["language"],
            "result_ids": session["result_ids"],
            "items": items,
            "total_paise": total,
            "currency": "INR",
            "is_demo": True,
            "pending_review": session["pending_review"] is not None,
            "review_delivered": session["review_delivery_id"] is not None,
            "pending_budget_exception": session["pending_budget"] is not None,
            "turn_seq": session["turn_seq"],
            "last_order_id": str(last_order["id"]) if last_order else None,
        }

    async def get_state(self):
        async def read(connection, session):
            return {"status": "ok"}

        return await self._run(read)

    async def record_user_message(self, message_id: UUID):
        async def record(connection, session):
            message = str(valid_uuid(message_id))
            if message in session["message_ids"]:
                return {
                    "status": "ok",
                    "message_seq": session["message_ids"].index(message) + 1,
                }
            changes = {
                "turn_seq": session["turn_seq"] + 1,
                "latest_message_id": valid_uuid(message),
                "message_ids": [*session["message_ids"], message],
            }
            if session["pending_review"] and not session["review_delivery_id"]:
                changes.update(
                    pending_review=None,
                    pending_token_hash=None,
                    review_delivery_id=None,
                )
            await save_session(connection, session, changes)
            return {"status": "ok", "message_seq": session["turn_seq"]}

        return await self._run(record)

    @staticmethod
    def _later_approval(session, message_id, after_seq):
        if (
            valid_uuid(message_id) != session["latest_message_id"]
            or session["turn_seq"] <= after_seq
        ):
            raise Refusal("later_user_approval_required")

    async def _candidate(self, connection, session, product_id, quantity):
        items = await self._items(connection, session)
        candidate = [item for item in items if item["product_id"] != product_id]
        if quantity:
            cursor = await connection.execute(
                "select p.uniq_id as product_id, p.product_name, p.discounted_price, i.available, %s::integer as quantity "
                "from public.products p left join public.demo_inventory i on i.product_id = p.uniq_id "
                "where p.uniq_id = %s",
                (quantity, product_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise Refusal("not_found")
            candidate.append(cart_item(row))
        return sorted(candidate, key=lambda item: item["product_id"])

    @staticmethod
    async def _write_quantity(connection, session, product_id, quantity):
        if quantity:
            await connection.execute(
                "insert into public.cart_items (session_id, product_id, quantity) values (%s, %s, %s) "
                "on conflict (session_id, product_id) do update set quantity = excluded.quantity",
                (session["id"], product_id, quantity),
            )
        else:
            await connection.execute(
                "delete from public.cart_items where session_id = %s and product_id = %s",
                (session["id"], product_id),
            )

    async def _budget_proposal(
        self, connection, session, snapshot, *, kind, product_id=None, quantity=None
    ):
        if not session["latest_message_id"]:
            raise Refusal("user_turn_required")
        token = secrets.token_urlsafe(32)
        proposal = {
            "token_hash": token_hash(token),
            "version": session["version"],
            "turn_seq": session["turn_seq"],
            "snapshot": snapshot,
            "kind": kind,
            "product_id": product_id,
            "quantity": quantity,
        }
        await save_session(
            connection,
            session,
            {
                "pending_budget": proposal,
                "pending_review": None,
                "pending_token_hash": None,
                "review_delivery_id": None,
            },
        )
        return {
            "status": "over_budget",
            "exception_token": token,
            "proposed_total_paise": snapshot["total_paise"],
        }

    async def _change(self, connection, session, *, product_id, quantity, operation):
        if (
            not isinstance(product_id, str)
            or not product_id.strip()
            or len(product_id) > 128
        ):
            raise Refusal("invalid_input")
        product_id = product_id.strip()
        if (
            type(quantity) is not int
            or not 0 <= quantity <= 1000000
            or (operation == "add" and quantity == 0)
        ):
            raise Refusal("invalid_quantity")
        old = await self._items(connection, session)
        current = next(
            (item["quantity"] for item in old if item["product_id"] == product_id), 0
        )
        target = current + quantity if operation == "add" else quantity
        if current == target:
            return {"status": "ok", "changed": False}
        candidate = await self._candidate(connection, session, product_id, target)
        snapshot = quote(candidate)
        budget = session["budget_paise"]
        over = budget is not None and snapshot["total_paise"] > budget
        reducing_approved = False
        if over and old and all(item["unit_price_paise"] is not None for item in old):
            old_snapshot = quote(old, check_stock=False)
            reducing_approved = snapshot["total_paise"] < old_snapshot[
                "total_paise"
            ] and session["budget_authorization"] == budget_digest(old_snapshot, budget)
        if over and not reducing_approved:
            return await self._budget_proposal(
                connection,
                session,
                snapshot,
                kind="cart",
                product_id=product_id,
                quantity=target,
            )
        await self._write_quantity(connection, session, product_id, target)
        await save_session(connection, session, {}, bump=True, invalidate=True)
        if over:
            await save_session(
                connection,
                session,
                {"budget_authorization": budget_digest(snapshot, budget)},
            )
        return {"status": "ok", "changed": True}

    async def add_item(self, product_id, quantity, expected_version):
        return await self._run(
            self._change,
            expected=expected_version,
            mutation=True,
            product_id=product_id,
            quantity=quantity,
            operation="add",
        )

    async def set_quantity(self, product_id, quantity, expected_version):
        return await self._run(
            self._change,
            expected=expected_version,
            mutation=True,
            product_id=product_id,
            quantity=quantity,
            operation="set",
        )

    async def remove_item(self, product_id, expected_version):
        return await self.set_quantity(product_id, 0, expected_version)

    async def set_budget(self, budget_paise, expected_version):
        async def change(connection, session):
            if budget_paise is not None and (
                type(budget_paise) is not int or not 0 <= budget_paise < 10**16
            ):
                raise Refusal("invalid_budget")
            if session["budget_paise"] == budget_paise:
                return {"status": "ok", "changed": False}
            await save_session(
                connection,
                session,
                {"budget_paise": budget_paise},
                bump=True,
                invalidate=True,
            )
            return {"status": "ok", "changed": True}

        return await self._run(change, expected=expected_version, mutation=True)

    async def set_address(self, patch, expected_version):
        async def change(connection, session):
            address = address_patch(session["address"], patch)
            if session["address"] == address:
                return {"status": "ok", "changed": False}
            await save_session(
                connection, session, {"address": address}, bump=True, invalidate=True
            )
            return {"status": "ok", "changed": True}

        return await self._run(change, expected=expected_version, mutation=True)

    async def approve_budget_exception(
        self, token, expected_version, approval_message_id
    ):
        async def approve(connection, session):
            pending = session["pending_budget"]
            if (
                not pending
                or pending["token_hash"] != token_hash(token)
                or pending["version"] != session["version"]
            ):
                raise Refusal("stale_exception")
            self._later_approval(session, approval_message_id, pending["turn_seq"])
            if pending["kind"] == "cart":
                items = await self._candidate(
                    connection, session, pending["product_id"], pending["quantity"]
                )
            else:
                items = await self._items(connection, session)
            snapshot = quote(items)
            if snapshot != pending["snapshot"]:
                await save_session(connection, session, {"pending_budget": None})
                return {"status": "price_changed"}
            if pending["kind"] == "cart":
                await self._write_quantity(
                    connection, session, pending["product_id"], pending["quantity"]
                )
                await save_session(connection, session, {}, bump=True, invalidate=True)
            await save_session(
                connection,
                session,
                {
                    "pending_budget": None,
                    "budget_authorization": budget_digest(
                        snapshot, session["budget_paise"]
                    ),
                },
            )
            return {"status": "ok", "changed": pending["kind"] == "cart"}

        return await self._run(approve, expected=expected_version, mutation=True)

    async def update_context(
        self,
        expected_version,
        *,
        add_instruction=None,
        remove_instruction=None,
        language=None,
        result_ids=None,
    ):
        async def change(connection, session):
            updates = {}
            instructions = list(session["instructions"])
            for instruction in (add_instruction, remove_instruction):
                if instruction is not None and (
                    not isinstance(instruction, str)
                    or not instruction.strip()
                    or len(instruction) > 500
                ):
                    raise Refusal("invalid_input")
            if (
                add_instruction is not None
                and add_instruction.strip() not in instructions
            ):
                instructions.append(add_instruction.strip())
            if (
                remove_instruction is not None
                and remove_instruction.strip() in instructions
            ):
                instructions.remove(remove_instruction.strip())
            if len(instructions) > 50:
                raise Refusal("invalid_input")
            if instructions != session["instructions"]:
                updates["instructions"] = instructions
            if language is not None:
                if not isinstance(language, str) or language not in {
                    "en",
                    "te",
                    "mixed",
                }:
                    raise Refusal("invalid_input")
                if language != session["language"]:
                    updates["language"] = language
            if result_ids is not None:
                if (
                    not isinstance(result_ids, list)
                    or len(result_ids) > 10
                    or any(
                        not isinstance(p, str) or not p or len(p) > 128
                        for p in result_ids
                    )
                    or len(set(result_ids)) != len(result_ids)
                ):
                    raise Refusal("invalid_input")
                cursor = await connection.execute(
                    "select uniq_id from public.products where uniq_id = any(%s)",
                    (result_ids,),
                )
                if len(await cursor.fetchall()) != len(result_ids):
                    raise Refusal("not_found")
                if result_ids != session["result_ids"]:
                    updates["result_ids"] = result_ids
            if updates:
                await save_session(
                    connection, session, updates, bump=True, invalidate=True
                )
            return {"status": "ok", "changed": bool(updates)}

        return await self._run(change, expected=expected_version, mutation=True)

    async def resolve_reference(self, position, expected_version):
        async def resolve(connection, session):
            if type(position) is not int or not 1 <= position <= len(
                session["result_ids"]
            ):
                raise Refusal("not_found")
            return {"status": "ok", "product_id": session["result_ids"][position - 1]}

        return await self._run(resolve, expected=expected_version, mutation=True)
