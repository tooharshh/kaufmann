lock table public.products in access exclusive mode;
do $$
begin
    if exists (select 1 from public.products limit 1) then
        raise exception 'Products must be empty before replacing the catalog schema';
    end if;
end;
$$;

drop table public.products;
create table public.products (
    uniq_id text primary key check (btrim(uniq_id) <> ''),
    crawl_timestamp timestamptz,
    product_url text,
    product_name text not null check (btrim(product_name) <> ''),
    product_category_tree text,
    pid text,
    retail_price numeric(14, 2),
    discounted_price numeric(14, 2),
    image text,
    "is_FK_Advantage_product" boolean,
    product_rating text,
    overall_rating text,
    product_specifications text
);

alter table public.products enable row level security;
revoke all on public.products from public, anon, authenticated;
grant select on public.products to authenticated;
create policy products_authenticated_read on public.products
    for select to authenticated using (true);
