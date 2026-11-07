create table public.products (
    id text primary key check (btrim(id) <> ''),
    name text not null check (btrim(name) <> ''),
    name_te text,
    category_path text[] not null check (cardinality(category_path) > 0),
    brand text,
    description text,
    price_paise bigint not null check (price_paise > 0),
    currency text not null check (currency = 'INR'),
    images jsonb not null check (jsonb_typeof(images) = 'array'),
    specifications_raw text,
    source jsonb not null check (jsonb_typeof(source) = 'object')
);

alter table public.products enable row level security;
revoke all on public.products from public, anon, authenticated;
grant select on public.products to authenticated;
create policy products_authenticated_read on public.products
    for select to authenticated using (true);
