"""Delivery changes require a spoken proposal and a later approval."""

import secrets

from src.state.persistence import save_session
from src.state.session import Refusal, address_patch, token_hash


class DeliveryMixin:
    async def propose_address(self, patch, expected_version):
        async def propose(connection, session):
            if not session["latest_message_id"]:
                raise Refusal("user_turn_required")
            address = address_patch(session["address"], patch)
            token = secrets.token_urlsafe(32)
            pending = {
                "address": address,
                "version": session["version"],
                "turn_seq": session["turn_seq"],
                "token_hash": token_hash(token),
                "delivered": False,
            }
            await save_session(
                connection, session, {"pending_address": pending}, invalidate=True
            )
            return {
                "status": "ok",
                "proposal_token": token,
                "proposed_address": address,
                "missing_fields": [
                    key
                    for key in ("recipient", "line1", "city", "state", "postal_code")
                    if not address.get(key)
                ],
            }

        return await self._run(propose, expected=expected_version, mutation=True)

    async def record_address_delivery(self, token):
        async def delivered(connection, session):
            pending = session["pending_address"]
            if not pending or pending["token_hash"] != token_hash(token):
                raise Refusal("stale_proposal")
            if (
                pending["turn_seq"] != session["turn_seq"]
                or pending["version"] != session["version"]
            ):
                raise Refusal("proposal_interrupted")
            await save_session(
                connection, session, {"pending_address": {**pending, "delivered": True}}
            )
            return {"status": "ok"}

        return await self._run(delivered)

    async def approve_address(self, token, expected_version, approval_message_id):
        async def approve(connection, session):
            pending = session["pending_address"]
            if (
                not pending
                or pending["token_hash"] != token_hash(token)
                or pending["version"] != session["version"]
            ):
                raise Refusal("stale_proposal")
            if not pending["delivered"]:
                raise Refusal("proposal_not_delivered")
            self._later_approval(session, approval_message_id, pending["turn_seq"])
            changed = pending["address"] != session["address"]
            await save_session(
                connection,
                session,
                {"address": pending["address"], "pending_address": None},
                bump=changed,
                invalidate=True,
            )
            return {"status": "ok", "changed": changed, "saved_to_address_book": False}

        return await self._run(approve, expected=expected_version, mutation=True)

    async def cancel_address(self, expected_version):
        async def cancel(connection, session):
            await save_session(connection, session, {"pending_address": None})
            return {"status": "ok"}

        return await self._run(cancel, expected=expected_version, mutation=True)
