-- Additive local migration. Review before applying to shared Supabase.
create table public.catalog_versions (
    id uuid primary key,
    name text not null check (length(name) between 1 and 100),
    status text not null default 'staging' check (status in ('staging', 'ready')),
    provenance jsonb not null default '{}' check (jsonb_typeof(provenance) = 'object'),
    created_at timestamptz not null default now()
);
insert into public.catalog_versions (id, name, status, provenance) values
('00000000-0000-0000-0000-000000000001', 'Default catalog', 'ready', '{"adapter":"legacy_flipkart"}');

alter table public.products
    add column catalog_id uuid not null default '00000000-0000-0000-0000-000000000001' references public.catalog_versions(id),
    add column source_product_id text,
    add column name_te text,
    add column description text,
    add column brand text,
    add column attributes jsonb not null default '{}' check (jsonb_typeof(attributes) = 'object'),
    add column variants jsonb,
    add column provenance jsonb not null default '{}' check (jsonb_typeof(provenance) = 'object'),
    add column search_document tsvector generated always as (to_tsvector('english',
        coalesce(product_name, '') || ' ' || coalesce(product_category_tree, '') || ' ' ||
        coalesce(description, '') || ' ' || coalesce(brand, '') || ' ' || coalesce(name_te, ''))) stored;
update public.products set source_product_id = uniq_id;
create unique index products_catalog_source_idx on public.products(catalog_id, source_product_id);
create index products_catalog_price_idx on public.products(catalog_id, discounted_price, uniq_id);
create index products_search_idx on public.products using gin(search_document);

-- The historical table name is retained for compatibility; imported stock can be supplied or demo.
alter table public.demo_inventory drop constraint demo_inventory_is_demo_check;

create table public.catalog_grants (
    user_id uuid not null references auth.users(id) on delete cascade,
    catalog_id uuid not null references public.catalog_versions(id),
    primary key(user_id, catalog_id)
);
create index catalog_grants_catalog_idx on public.catalog_grants(catalog_id);
create table public.catalog_selections (
    user_id uuid primary key references auth.users(id) on delete cascade,
    catalog_id uuid not null default '00000000-0000-0000-0000-000000000001' references public.catalog_versions(id),
    generation bigint not null default 0 check (generation >= 0)
);
create index catalog_selections_catalog_idx on public.catalog_selections(catalog_id);
alter table public.shopping_sessions drop constraint shopping_sessions_user_id_key;
alter table public.shopping_sessions
    add column catalog_id uuid not null default '00000000-0000-0000-0000-000000000001' references public.catalog_versions(id),
    add column pending_address jsonb,
    add column shopping_task jsonb not null default '{}' check (jsonb_typeof(shopping_task) = 'object'),
    add column task_updated_at timestamptz not null default now(),
    add unique(user_id, catalog_id),
    add unique(id, catalog_id);
create index sessions_catalog_idx on public.shopping_sessions(catalog_id);
alter table public.products add unique(uniq_id, catalog_id);
alter table public.cart_items add column catalog_id uuid not null default '00000000-0000-0000-0000-000000000001';
alter table public.cart_items add foreign key(session_id, catalog_id) references public.shopping_sessions(id, catalog_id);
alter table public.cart_items add foreign key(product_id, catalog_id) references public.products(uniq_id, catalog_id);
alter table public.orders add column catalog_id uuid not null default '00000000-0000-0000-0000-000000000001' references public.catalog_versions(id);
alter table public.orders add foreign key(session_id, catalog_id) references public.shopping_sessions(id, catalog_id);
create index orders_catalog_idx on public.orders(catalog_id);

create table public.preference_memory (
    user_id uuid not null references auth.users(id) on delete cascade,
    subject text not null check (length(subject) between 1 and 80),
    scope text not null check (length(scope) between 1 and 80),
    key text not null check (key in ('size', 'language', 'brand', 'material', 'response_style')),
    value text not null check (length(value) between 1 and 160),
    source_turn uuid not null,
    revision uuid not null default gen_random_uuid(),
    updated_at timestamptz not null default now(),
    primary key(user_id, subject, scope, key)
);

alter table public.catalog_versions enable row level security;
alter table public.catalog_grants enable row level security;
alter table public.catalog_selections enable row level security;
alter table public.preference_memory enable row level security;
revoke all on public.catalog_versions, public.catalog_grants, public.catalog_selections, public.preference_memory from public, anon, authenticated;
grant select on public.catalog_versions, public.catalog_grants, public.catalog_selections, public.preference_memory to authenticated;
create policy grants_owner_read on public.catalog_grants for select to authenticated using(user_id = (select auth.uid()));
create policy selections_owner_read on public.catalog_selections for select to authenticated using(user_id = (select auth.uid()));
create policy memory_owner_read on public.preference_memory for select to authenticated using(user_id = (select auth.uid()));
create policy catalogs_authorized_read on public.catalog_versions for select to authenticated using(
    status = 'ready' and (id = '00000000-0000-0000-0000-000000000001' or exists(
        select 1 from public.catalog_grants g where g.catalog_id = id and g.user_id = (select auth.uid()))));
drop policy products_authenticated_read on public.products;
create policy products_authorized_read on public.products for select to authenticated using(
    exists(select 1 from public.catalog_versions v where v.id = catalog_id));
drop policy demo_inventory_read on public.demo_inventory;
create policy inventory_authorized_read on public.demo_inventory for select to authenticated using(
    exists(select 1 from public.products p where p.uniq_id = product_id));

-- Ready imports cannot be rewritten. Legacy seeding remains supported in the default catalog.
create function public.protect_catalog_version() returns trigger language plpgsql set search_path = '' as $$
begin
    if TG_OP <> 'INSERT' and OLD.catalog_id <> '00000000-0000-0000-0000-000000000001' and
        exists(select 1 from public.catalog_versions where id = OLD.catalog_id and status = 'ready') then
        raise exception 'Catalog versions are immutable';
    end if;
    if TG_OP <> 'DELETE' and NEW.catalog_id <> '00000000-0000-0000-0000-000000000001' and
        exists(select 1 from public.catalog_versions where id = NEW.catalog_id and status = 'ready') then
        raise exception 'Catalog versions are immutable';
    end if;
    if TG_OP = 'DELETE' then return OLD; end if;
    return NEW;
end;
$$;
revoke execute on function public.protect_catalog_version() from public, anon, authenticated;
create trigger products_immutable before insert or update or delete on public.products
    for each row execute function public.protect_catalog_version();

-- Epoch protects an explicit correction/forget from queued automatic extraction.
create table public.memory_control (
    user_id uuid primary key references auth.users(id) on delete cascade,
    revision bigint not null default 0 check (revision >= 0)
);
alter table public.memory_control enable row level security;
revoke all on public.memory_control from public, anon, authenticated;
grant select on public.memory_control to authenticated;
create policy memory_control_owner_read on public.memory_control for select to authenticated using(user_id = (select auth.uid()));
