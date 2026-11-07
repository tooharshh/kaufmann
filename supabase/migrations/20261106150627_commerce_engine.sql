create table public.shopping_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null unique references auth.users(id),
    version bigint not null default 0 check (version >= 0),
    budget_paise bigint check (budget_paise >= 0),
    address jsonb,
    instructions jsonb not null default '[]' check (jsonb_typeof(instructions) = 'array'),
    language text not null default 'en',
    result_ids jsonb not null default '[]' check (jsonb_typeof(result_ids) = 'array'),
    pending_review jsonb,
    pending_token_hash text,
    review_delivery_id uuid,
    pending_budget jsonb,
    budget_authorization text,
    turn_seq bigint not null default 0,
    message_ids jsonb not null default '[]',
    latest_message_id uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (address is null or jsonb_typeof(address) = 'object')
);

create table public.cart_items (
    session_id uuid not null references public.shopping_sessions(id),
    product_id text not null references public.products(uniq_id),
    quantity integer not null check (quantity > 0),
    primary key (session_id, product_id)
);
create index cart_items_product_idx on public.cart_items(product_id);

create table public.demo_inventory (
    product_id text primary key references public.products(uniq_id),
    available integer not null check (available >= 0),
    is_demo boolean not null default true check (is_demo)
);

insert into public.demo_inventory (product_id, available)
select uniq_id, 10 from public.products
where discounted_price > 0 and discounted_price <> 'NaN'::numeric;

create table public.orders (
    id uuid primary key,
    user_id uuid not null references auth.users(id),
    session_id uuid not null references public.shopping_sessions(id),
    confirmation_hash text not null unique,
    total_paise bigint not null check (total_paise > 0),
    address jsonb not null check (jsonb_typeof(address) = 'object'),
    snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
    status text not null default 'demo_confirmed' check (status = 'demo_confirmed'),
    created_at timestamptz not null default now()
);
create index orders_user_created_idx on public.orders(user_id, created_at desc);
create index orders_session_idx on public.orders(session_id);

create table public.order_items (
    order_id uuid not null references public.orders(id),
    product_id text not null references public.products(uniq_id),
    product_name text not null,
    quantity integer not null check (quantity > 0),
    unit_price_paise bigint not null check (unit_price_paise > 0),
    line_total_paise bigint not null check (line_total_paise = quantity::bigint * unit_price_paise),
    primary key (order_id, product_id)
);
create index order_items_product_idx on public.order_items(product_id);

alter table public.shopping_sessions enable row level security;
alter table public.cart_items enable row level security;
alter table public.demo_inventory enable row level security;
alter table public.orders enable row level security;
alter table public.order_items enable row level security;

revoke all on public.shopping_sessions, public.cart_items, public.demo_inventory,
    public.orders, public.order_items from public, anon, authenticated;
grant select on public.shopping_sessions, public.cart_items, public.demo_inventory,
    public.orders, public.order_items to authenticated;

create policy sessions_owner_read on public.shopping_sessions for select to authenticated
    using (user_id = (select auth.uid()));
create policy cart_owner_read on public.cart_items for select to authenticated
    using (exists (select 1 from public.shopping_sessions s
        where s.id = session_id and s.user_id = (select auth.uid())));
create policy demo_inventory_read on public.demo_inventory for select to authenticated using (true);
create policy orders_owner_read on public.orders for select to authenticated
    using (user_id = (select auth.uid()));
create policy order_items_owner_read on public.order_items for select to authenticated
    using (exists (select 1 from public.orders o
        where o.id = order_id and o.user_id = (select auth.uid())));
