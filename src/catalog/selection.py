"""Catalog access comes from operator grants, never user-editable auth metadata."""

from uuid import UUID

from psycopg.rows import dict_row

from src.state.session import Refusal, valid_uuid

DEFAULT_CATALOG = UUID("00000000-0000-0000-0000-000000000001")


async def selected_catalog(connection, user_id):
    await connection.execute(
        "insert into public.catalog_selections(user_id) values (%s) on conflict do nothing",
        (user_id,),
    )
    cursor = await connection.execute(
        "select catalog_id, generation from public.catalog_selections where user_id = %s for share",
        (user_id,),
    )
    row = await cursor.fetchone()
    await authorize_catalog(connection, user_id, row["catalog_id"])
    return row


async def authorize_catalog(connection, user_id, catalog_id):
    cursor = await connection.execute(
        "select id from public.catalog_versions v where id = %s and status = 'ready' "
        "and (id = %s or exists(select 1 from public.catalog_grants g where g.catalog_id = v.id and g.user_id = %s))",
        (catalog_id, DEFAULT_CATALOG, user_id),
    )
    if not await cursor.fetchone():
        raise Refusal("catalog_not_authorized")


async def catalog_options(pool, user_id):
    async with pool.connection() as connection:
        connection.row_factory = dict_row
        selection = await selected_catalog(connection, user_id)
        cursor = await connection.execute(
            "select id, name, created_at from public.catalog_versions v where status = 'ready' "
            "and (id = %s or exists(select 1 from public.catalog_grants g where g.catalog_id = v.id and g.user_id = %s)) order by created_at",
            (DEFAULT_CATALOG, user_id),
        )
        return {
            "status": "ok",
            "catalog_id": str(selection["catalog_id"]),
            "generation": selection["generation"],
            "catalogs": [
                {"id": str(r["id"]), "name": r["name"]} for r in await cursor.fetchall()
            ],
        }


async def select_catalog(pool, user_id, catalog_id):
    catalog_id = valid_uuid(catalog_id)
    async with pool.connection() as connection, connection.transaction():
        connection.row_factory = dict_row
        await authorize_catalog(connection, user_id, catalog_id)
        await connection.execute(
            "insert into public.catalog_selections(user_id) values (%s) on conflict do nothing",
            (user_id,),
        )
        cursor = await connection.execute(
            "select * from public.catalog_selections where user_id = %s for update",
            (user_id,),
        )
        old = await cursor.fetchone()
        changed = old["catalog_id"] != catalog_id
        if changed:
            # Invalidate both old and restored reviews. Switching back never revives approval.
            await connection.execute(
                "update public.shopping_sessions set pending_review = null, pending_token_hash = null, review_delivery_id = null, pending_address = null, pending_budget = null, budget_authorization = null, version = version + 1 where user_id = %s and catalog_id = any(%s)",
                (user_id, [old["catalog_id"], catalog_id]),
            )
            await connection.execute(
                "update public.catalog_selections set catalog_id = %s, generation = generation + 1 where user_id = %s",
                (catalog_id, user_id),
            )
        return {
            "status": "ok",
            "changed": changed,
            "catalog_id": str(catalog_id),
            "generation": old["generation"] + int(changed),
            "end_voice_session": changed,
        }
