-- Optional additive search index. Application rollback needs no schema rollback.
create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table public.product_embeddings (
    product_id text not null,
    catalog_id uuid not null,
    profile text not null check (profile = 'gemini-embedding-2:768:catalog-v1'),
    content_hash text not null check (length(content_hash) = 64),
    embedding extensions.vector(768) not null,
    updated_at timestamptz not null default now(),
    primary key (catalog_id, product_id, profile),
    foreign key (product_id, catalog_id) references public.products(uniq_id, catalog_id) on delete cascade
);
alter table public.product_embeddings enable row level security;
-- Backend SQL only. Raw vectors are not a public Data API resource.
revoke all on public.product_embeddings from public, anon, authenticated;

create function public.invalidate_product_embedding() returns trigger
language plpgsql set search_path = '' as $$
begin
    if row(OLD.product_name, OLD.name_te, OLD.product_category_tree, OLD.description,
           OLD.brand, OLD.attributes, OLD.product_specifications)
       is distinct from
       row(NEW.product_name, NEW.name_te, NEW.product_category_tree, NEW.description,
           NEW.brand, NEW.attributes, NEW.product_specifications) then
        delete from public.product_embeddings where product_id = OLD.uniq_id and catalog_id = OLD.catalog_id;
    end if;
    return NEW;
end;
$$;
revoke execute on function public.invalidate_product_embedding() from public, anon, authenticated;
create trigger products_embedding_invalidation after update on public.products
    for each row execute function public.invalidate_product_embedding();
