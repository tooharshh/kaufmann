from psycopg import sql
from psycopg.types.json import Jsonb

JSON_FIELDS = {
    "address",
    "instructions",
    "result_ids",
    "pending_review",
    "pending_budget",
    "message_ids",
    "pending_address",
    "shopping_task",
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


async def load_session(connection, user_id, catalog_id):
    await connection.execute(
        "insert into public.shopping_sessions (user_id, catalog_id) values (%s, %s) on conflict (user_id, catalog_id) do nothing",
        (user_id, catalog_id),
    )
    cursor = await connection.execute(
        "select * from public.shopping_sessions where user_id = %s and catalog_id = %s for update",
        (user_id, catalog_id),
    )
    session = await cursor.fetchone()
    expired = await connection.execute(
        "select task_updated_at < now() - interval '7 days' as expired from public.shopping_sessions where id = %s",
        (session["id"],),
    )
    if (await expired.fetchone())["expired"] and session["shopping_task"]:
        await connection.execute(
            "update public.shopping_sessions set shopping_task = '{}'::jsonb, result_ids = '[]'::jsonb where id = %s",
            (session["id"],),
        )
        session.update(shopping_task={}, result_ids=[])
    return session


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
    if bump and invalidate and "pending_address" not in changes:
        changes["pending_address"] = None
    if bump:
        changes["version"] = session["version"] + 1
    if not changes or changes.keys() - FIELDS:
        raise ValueError("Invalid session update")
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(name)) for name in changes
    )
    if "shopping_task" in changes:
        assignments += sql.SQL(", task_updated_at = now()")
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
