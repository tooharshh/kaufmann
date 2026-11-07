from psycopg import sql
from psycopg.types.json import Jsonb

JSON_FIELDS = {
    "address",
    "instructions",
    "result_ids",
    "pending_review",
    "pending_budget",
    "message_ids",
}
FIELDS = JSON_FIELDS | {
    "version",
    "budget_paise",
    "language",
    "pending_token_hash",
    "review_delivery_id",
    "budget_authorization",
    "turn_seq",
    "latest_message_id",
}


async def load_session(connection, user_id):
    await connection.execute(
        "insert into public.shopping_sessions (user_id) values (%s) on conflict (user_id) do nothing",
        (user_id,),
    )
    cursor = await connection.execute(
        "select * from public.shopping_sessions where user_id = %s for update",
        (user_id,),
    )
    return await cursor.fetchone()


async def save_session(connection, session, changes, *, bump=False, invalidate=False):
    changes = dict(changes)
    if invalidate:
        changes.update(
            pending_review=None,
            pending_token_hash=None,
            review_delivery_id=None,
            pending_budget=None,
            budget_authorization=None,
        )
    if bump:
        changes["version"] = session["version"] + 1
    if not changes or changes.keys() - FIELDS:
        raise ValueError("Invalid session update")
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(name)) for name in changes
    )
    values = [
        Jsonb(value) if name in JSON_FIELDS and value is not None else value
        for name, value in changes.items()
    ]
    await connection.execute(
        sql.SQL(
            "update public.shopping_sessions set {}, updated_at = now() where id = %s"
        ).format(assignments),
        (*values, session["id"]),
    )
    session.update(changes)
