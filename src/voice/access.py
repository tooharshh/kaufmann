import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from uuid import UUID, uuid4

from livekit import api

AGENT_NAME = "kaufmann-shopping"


def dispatch_metadata(user_id, room, secret, *, now=None):
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "room": room,
            "expires": int(now or time.time()) + 600,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return json.dumps({"payload": encoded, "signature": signature})


def verify_dispatch(metadata, room, secret, *, now=None):
    try:
        envelope = json.loads(metadata)
        payload = base64.b64decode(envelope["payload"], altchars=b"-_", validate=True)
        signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, envelope["signature"]):
            raise ValueError
        data = json.loads(payload)
        if (
            data["room"] != room
            or not int(now or time.time())
            < data["expires"]
            <= int(now or time.time()) + 600
        ):
            raise ValueError
        return UUID(data["user_id"])
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise ValueError("Invalid voice session authorization") from None


def voice_session(settings, user_id):
    room = "kaufmann-" + uuid4().hex
    identity = "shopper:" + str(user_id)
    token = (
        api.AccessToken(settings["LIVEKIT_API_KEY"], settings["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_ttl(timedelta(minutes=10))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
                can_update_own_metadata=False,
                can_publish_sources=["microphone"],
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                max_participants=2,
                empty_timeout=60,
                departure_timeout=20,
                agents=[
                    api.RoomAgentDispatch(
                        agent_name=AGENT_NAME,
                        metadata=dispatch_metadata(
                            user_id, room, settings["VOICE_DISPATCH_SECRET"]
                        ),
                    )
                ],
            )
        )
        .to_jwt()
    )
    return {
        "status": "ok",
        "url": settings["LIVEKIT_URL"],
        "token": token,
        "room": room,
        "identity": identity,
    }
