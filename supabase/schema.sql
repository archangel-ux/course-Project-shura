-- Qoima — Supabase schema.
-- Run once: Supabase Dashboard → SQL Editor → New query → paste this file → Run.
-- Safe to re-run. Tables use the "qoima_" prefix so they never clash with other tables in the project.
--
-- Money is stored as BIGINT tiyn (1 ₸ = 100 tiyn). Quantities are whole numbers.
-- Product quantity can only change through the RPC functions below, so the balance
-- and the movement history are always updated together in one transaction.

-- ---------------------------------------------------------------- tables

create table if not exists public.qoima_profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    full_name text not null default '' check (char_length(full_name) <= 120),
    company text not null default '' check (char_length(company) <= 120),
    phone text not null default '' check (char_length(phone) <= 40),
    language text not null default 'kk' check (language in ('kk', 'ru', 'en')),
    theme text not null default 'dark' check (theme in ('dark', 'light')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.qoima_suppliers (
    id bigint generated always as identity primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    name text not null check (char_length(btrim(name)) between 1 and 150),
    contact_person text not null default '' check (char_length(contact_person) <= 120),
    phone text not null default '' check (char_length(phone) <= 40),
    email text not null default '' check (char_length(email) <= 120),
    note text not null default '' check (char_length(note) <= 500),
    created_at timestamptz not null default now()
);
create unique index if not exists qoima_suppliers_owner_name on public.qoima_suppliers (owner_id, lower(name));

create table if not exists public.qoima_products (
    id bigint generated always as identity primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    name text not null check (char_length(btrim(name)) between 1 and 150),
    sku text not null check (char_length(btrim(sku)) between 1 and 50),
    category text not null default '' check (char_length(category) <= 80),
    unit text not null default 'дана' check (char_length(unit) between 1 and 20),
    quantity integer not null default 0 check (quantity >= 0),
    min_quantity integer not null default 0 check (min_quantity >= 0),
    purchase_price bigint not null default 0 check (purchase_price >= 0),
    sale_price bigint not null default 0 check (sale_price >= 0),
    description text not null default '' check (char_length(description) <= 1000),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create unique index if not exists qoima_products_owner_sku on public.qoima_products (owner_id, lower(sku));

create table if not exists public.qoima_movements (
    id bigint generated always as identity primary key,
    owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    product_id bigint not null references public.qoima_products (id) on delete restrict,
    movement_type text not null check (movement_type in ('IN', 'OUT', 'ADJUST')),
    quantity integer not null,
    balance_after integer not null check (balance_after >= 0),
    supplier_id bigint references public.qoima_suppliers (id) on delete restrict,
    note text not null default '' check (char_length(note) <= 200),
    created_at timestamptz not null default now(),
    -- IN/OUT are always positive; ADJUST (stocktake) is the signed difference
    constraint qoima_movements_quantity_sign
        check (quantity <> 0 and (movement_type = 'ADJUST' or quantity > 0))
);
create index if not exists qoima_movements_owner_created on public.qoima_movements (owner_id, created_at desc);
create index if not exists qoima_movements_product on public.qoima_movements (product_id);

-- ---------------------------------------------------------------- row level security

alter table public.qoima_profiles enable row level security;
alter table public.qoima_suppliers enable row level security;
alter table public.qoima_products enable row level security;
alter table public.qoima_movements enable row level security;

drop policy if exists "own profile" on public.qoima_profiles;
create policy "own profile" on public.qoima_profiles
    for all to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));

drop policy if exists "own suppliers" on public.qoima_suppliers;
create policy "own suppliers" on public.qoima_suppliers
    for all to authenticated
    using (owner_id = (select auth.uid()))
    with check (owner_id = (select auth.uid()));

drop policy if exists "read own products" on public.qoima_products;
create policy "read own products" on public.qoima_products
    for select to authenticated
    using (owner_id = (select auth.uid()));

drop policy if exists "edit own products" on public.qoima_products;
create policy "edit own products" on public.qoima_products
    for update to authenticated
    using (owner_id = (select auth.uid()))
    with check (owner_id = (select auth.uid()));

drop policy if exists "read own movements" on public.qoima_movements;
create policy "read own movements" on public.qoima_movements
    for select to authenticated
    using (owner_id = (select auth.uid()));

-- ---------------------------------------------------------------- privileges
-- Products are created and their quantity changed only via RPC; plain UPDATE may touch
-- the card fields but never "quantity". Movements are read-only from the API.

revoke all on public.qoima_profiles, public.qoima_suppliers, public.qoima_products, public.qoima_movements
    from anon, authenticated;

grant select, insert, update on public.qoima_profiles to authenticated;
grant select, insert, update, delete on public.qoima_suppliers to authenticated;
grant select on public.qoima_products to authenticated;
grant update (name, sku, category, unit, min_quantity, purchase_price, sale_price, description, is_active, updated_at)
    on public.qoima_products to authenticated;
grant select on public.qoima_movements to authenticated;

-- ---------------------------------------------------------------- new user → profile

create or replace function public.qoima_handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_language text := coalesce(new.raw_user_meta_data ->> 'language', 'kk');
begin
    if v_language not in ('kk', 'ru', 'en') then
        v_language := 'kk';
    end if;
    insert into public.qoima_profiles (id, full_name, language)
    values (new.id, left(coalesce(new.raw_user_meta_data ->> 'full_name', ''), 120), v_language)
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists qoima_on_auth_user_created on auth.users;
create trigger qoima_on_auth_user_created
    after insert on auth.users
    for each row execute function public.qoima_handle_new_user();

-- ---------------------------------------------------------------- sign-up without email confirmation
-- New accounts are confirmed at once, so registration signs the user straight in.
-- (Also switch off Authentication → Sign In / Providers → Email → "Confirm email",
--  otherwise Supabase still tries to send a confirmation letter.)

create or replace function public.qoima_autoconfirm_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    new.email_confirmed_at := coalesce(new.email_confirmed_at, now());
    return new;
end;
$$;

drop trigger if exists qoima_autoconfirm on auth.users;
create trigger qoima_autoconfirm
    before insert on auth.users
    for each row execute function public.qoima_autoconfirm_user();

-- accounts that registered earlier and are still waiting for the letter
update auth.users set email_confirmed_at = now() where email_confirmed_at is null;

-- ---------------------------------------------------------------- RPC: create product

create or replace function public.qoima_create_product(
    p_name text,
    p_sku text,
    p_category text,
    p_unit text,
    p_min_quantity integer,
    p_purchase_price bigint,
    p_sale_price bigint,
    p_description text,
    p_initial_quantity integer default 0,
    p_note text default ''
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_owner uuid := auth.uid();
    v_id bigint;
begin
    if v_owner is null then
        raise exception 'NOT_AUTHENTICATED';
    end if;
    if p_initial_quantity is null or p_initial_quantity < 0 then
        raise exception 'INVALID_QUANTITY';
    end if;

    insert into public.qoima_products
        (owner_id, name, sku, category, unit, min_quantity, purchase_price, sale_price, description, quantity)
    values
        (v_owner, btrim(p_name), btrim(p_sku), coalesce(btrim(p_category), ''),
         coalesce(nullif(btrim(p_unit), ''), 'дана'), coalesce(p_min_quantity, 0),
         coalesce(p_purchase_price, 0), coalesce(p_sale_price, 0), coalesce(p_description, ''),
         p_initial_quantity)
    returning id into v_id;

    if p_initial_quantity > 0 then
        insert into public.qoima_movements (owner_id, product_id, movement_type, quantity, balance_after, note)
        values (v_owner, v_id, 'IN', p_initial_quantity, p_initial_quantity, coalesce(p_note, ''));
    end if;

    return v_id;
end;
$$;

-- ---------------------------------------------------------------- RPC: stock in / out

create or replace function public.qoima_register_movement(
    p_product_id bigint,
    p_type text,
    p_quantity integer,
    p_note text default '',
    p_supplier_id bigint default null
)
returns public.qoima_movements
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_owner uuid := auth.uid();
    v_product public.qoima_products;
    v_new_quantity integer;
    v_row public.qoima_movements;
begin
    if v_owner is null then
        raise exception 'NOT_AUTHENTICATED';
    end if;
    if p_type not in ('IN', 'OUT') then
        raise exception 'INVALID_TYPE';
    end if;
    if p_quantity is null or p_quantity <= 0 then
        raise exception 'INVALID_QUANTITY';
    end if;

    -- lock the row so two simultaneous OUT operations cannot both pass the check
    select * into v_product
    from public.qoima_products
    where id = p_product_id and owner_id = v_owner
    for update;

    if not found then
        raise exception 'NOT_FOUND';
    end if;
    if not v_product.is_active then
        raise exception 'PRODUCT_INACTIVE';
    end if;
    if p_supplier_id is not null and not exists (
        select 1 from public.qoima_suppliers where id = p_supplier_id and owner_id = v_owner
    ) then
        raise exception 'NOT_FOUND';
    end if;

    v_new_quantity := v_product.quantity + case when p_type = 'IN' then p_quantity else -p_quantity end;
    if v_new_quantity < 0 then
        raise exception 'INSUFFICIENT_STOCK';
    end if;

    update public.qoima_products set quantity = v_new_quantity, updated_at = now() where id = p_product_id;

    insert into public.qoima_movements (owner_id, product_id, movement_type, quantity, balance_after, supplier_id, note)
    values (v_owner, p_product_id, p_type, p_quantity, v_new_quantity,
            case when p_type = 'IN' then p_supplier_id end, coalesce(p_note, ''))
    returning * into v_row;

    return v_row;
end;
$$;

-- ---------------------------------------------------------------- RPC: stocktake (inventory count)

create or replace function public.qoima_stocktake(p_items jsonb, p_note text default '')
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_owner uuid := auth.uid();
    v_item jsonb;
    v_product public.qoima_products;
    v_counted integer;
    v_changed integer := 0;
begin
    if v_owner is null then
        raise exception 'NOT_AUTHENTICATED';
    end if;
    if jsonb_typeof(p_items) is distinct from 'array' then
        raise exception 'INVALID_INPUT';
    end if;

    for v_item in select value from jsonb_array_elements(p_items) loop
        v_counted := (v_item ->> 'counted')::integer;
        if v_counted is null or v_counted < 0 then
            raise exception 'INVALID_QUANTITY';
        end if;

        select * into v_product
        from public.qoima_products
        where id = (v_item ->> 'product_id')::bigint and owner_id = v_owner
        for update;

        if not found then
            raise exception 'NOT_FOUND';
        end if;

        if v_counted <> v_product.quantity then
            update public.qoima_products set quantity = v_counted, updated_at = now() where id = v_product.id;
            insert into public.qoima_movements (owner_id, product_id, movement_type, quantity, balance_after, note)
            values (v_owner, v_product.id, 'ADJUST', v_counted - v_product.quantity, v_counted, coalesce(p_note, ''));
            v_changed := v_changed + 1;
        end if;
    end loop;

    return v_changed;
end;
$$;

revoke all on function public.qoima_handle_new_user() from public, anon, authenticated;
revoke all on function public.qoima_autoconfirm_user() from public, anon, authenticated;
revoke all on function public.qoima_create_product(text, text, text, text, integer, bigint, bigint, text, integer, text) from public, anon;
revoke all on function public.qoima_register_movement(bigint, text, integer, text, bigint) from public, anon;
revoke all on function public.qoima_stocktake(jsonb, text) from public, anon;
grant execute on function public.qoima_create_product(text, text, text, text, integer, bigint, bigint, text, integer, text) to authenticated;
grant execute on function public.qoima_register_movement(bigint, text, integer, text, bigint) to authenticated;
grant execute on function public.qoima_stocktake(jsonb, text) to authenticated;

-- Profiles for users that registered before this script was run
insert into public.qoima_profiles (id, full_name)
select id, left(coalesce(raw_user_meta_data ->> 'full_name', ''), 120) from auth.users
on conflict (id) do nothing;

notify pgrst, 'reload schema';
