-- Qoima — Supabase schema (v2: organizations, roles, warehouses, documents, photos, notifications).
-- Run: Supabase Dashboard → SQL Editor → New query → paste this file → Run.
-- Safe to re-run, and safe to run over the v1 schema: existing data is moved into a
-- personal organization of its owner with one default warehouse.
--
-- Money is stored as BIGINT tiyn (1 ₸ = 100 tiyn). Quantities are whole numbers.
-- Stock can only change through the RPC functions below, so the per-warehouse stock,
-- the product total and the movement history are always updated in one transaction.
--
-- Access model: every row belongs to an organization. A user may be a member of several
-- organizations (one is "current", stored in the profile) with one of three roles:
--   owner       — everything, including the team, requisites and product cards
--   storekeeper — stock operations only (receipt, issue, transfer, stocktake)
--   accountant  — read-only access and reports

-- ---------------------------------------------------------------- organizations & members

create table if not exists public.qoima_organizations (
    id bigint generated always as identity primary key,
    name text not null default '' check (char_length(name) <= 150),
    bin text not null default '' check (char_length(bin) <= 20),
    address text not null default '' check (char_length(address) <= 250),
    phone text not null default '' check (char_length(phone) <= 40),
    bank text not null default '' check (char_length(bank) <= 150),
    iban text not null default '' check (char_length(iban) <= 40),
    bik text not null default '' check (char_length(bik) <= 20),
    director text not null default '' check (char_length(director) <= 120),
    created_by uuid default auth.uid() references auth.users (id) on delete set null,
    created_at timestamptz not null default now()
);

create table if not exists public.qoima_members (
    organization_id bigint not null references public.qoima_organizations (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    role text not null check (role in ('owner', 'storekeeper', 'accountant')),
    created_at timestamptz not null default now(),
    primary key (organization_id, user_id)
);
create index if not exists qoima_members_user on public.qoima_members (user_id);

create table if not exists public.qoima_invites (
    id bigint generated always as identity primary key,
    organization_id bigint not null references public.qoima_organizations (id) on delete cascade,
    email text not null check (char_length(email) between 3 and 120),
    role text not null check (role in ('owner', 'storekeeper', 'accountant')),
    token text not null unique default replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', ''),
    created_by uuid default auth.uid() references auth.users (id) on delete set null,
    created_at timestamptz not null default now(),
    accepted_at timestamptz
);

-- ---------------------------------------------------------------- profiles

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
alter table public.qoima_profiles
    add column if not exists organization_id bigint references public.qoima_organizations (id) on delete set null,
    add column if not exists telegram_chat_id bigint,
    add column if not exists notify_telegram boolean not null default true,
    add column if not exists notify_email boolean not null default false;

-- ---------------------------------------------------------------- warehouses

create table if not exists public.qoima_warehouses (
    id bigint generated always as identity primary key,
    organization_id bigint not null references public.qoima_organizations (id) on delete cascade,
    name text not null check (char_length(btrim(name)) between 1 and 100),
    address text not null default '' check (char_length(address) <= 250),
    created_at timestamptz not null default now()
);
create unique index if not exists qoima_warehouses_org_name on public.qoima_warehouses (organization_id, lower(name));

-- ---------------------------------------------------------------- suppliers, products, movements (v1 tables)

create table if not exists public.qoima_suppliers (
    id bigint generated always as identity primary key,
    owner_id uuid default auth.uid() references auth.users (id) on delete set null,
    name text not null check (char_length(btrim(name)) between 1 and 150),
    contact_person text not null default '' check (char_length(contact_person) <= 120),
    phone text not null default '' check (char_length(phone) <= 40),
    email text not null default '' check (char_length(email) <= 120),
    note text not null default '' check (char_length(note) <= 500),
    created_at timestamptz not null default now()
);

create table if not exists public.qoima_products (
    id bigint generated always as identity primary key,
    owner_id uuid default auth.uid() references auth.users (id) on delete set null,
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

create table if not exists public.qoima_movements (
    id bigint generated always as identity primary key,
    owner_id uuid default auth.uid() references auth.users (id) on delete set null,
    product_id bigint not null references public.qoima_products (id) on delete restrict,
    movement_type text not null,
    quantity integer not null,
    balance_after integer not null check (balance_after >= 0),
    supplier_id bigint references public.qoima_suppliers (id) on delete restrict,
    note text not null default '' check (char_length(note) <= 200),
    created_at timestamptz not null default now()
);

create table if not exists public.qoima_documents (
    id bigint generated always as identity primary key,
    organization_id bigint not null references public.qoima_organizations (id) on delete cascade,
    number integer not null,
    doc_type text not null check (doc_type in ('IN', 'OUT', 'TRANSFER', 'ADJUST')),
    warehouse_id bigint references public.qoima_warehouses (id) on delete restrict,
    to_warehouse_id bigint references public.qoima_warehouses (id) on delete restrict,
    supplier_id bigint references public.qoima_suppliers (id) on delete restrict,
    counterparty text not null default '' check (char_length(counterparty) <= 150),
    note text not null default '' check (char_length(note) <= 200),
    created_by uuid default auth.uid() references auth.users (id) on delete set null,
    created_at timestamptz not null default now(),
    unique (organization_id, doc_type, number)
);
create index if not exists qoima_documents_org_created on public.qoima_documents (organization_id, created_at desc);

-- v1 → v2: the user who created a row no longer owns it — the organization does.
alter table public.qoima_suppliers alter column owner_id drop not null;
alter table public.qoima_products alter column owner_id drop not null;
alter table public.qoima_movements alter column owner_id drop not null;
alter table public.qoima_suppliers drop constraint if exists qoima_suppliers_owner_id_fkey;
alter table public.qoima_suppliers add constraint qoima_suppliers_owner_id_fkey
    foreign key (owner_id) references auth.users (id) on delete set null;
alter table public.qoima_products drop constraint if exists qoima_products_owner_id_fkey;
alter table public.qoima_products add constraint qoima_products_owner_id_fkey
    foreign key (owner_id) references auth.users (id) on delete set null;
alter table public.qoima_movements drop constraint if exists qoima_movements_owner_id_fkey;
alter table public.qoima_movements add constraint qoima_movements_owner_id_fkey
    foreign key (owner_id) references auth.users (id) on delete set null;

alter table public.qoima_suppliers
    add column if not exists organization_id bigint references public.qoima_organizations (id) on delete cascade;
alter table public.qoima_products
    add column if not exists organization_id bigint references public.qoima_organizations (id) on delete cascade,
    add column if not exists photo_path text not null default '';
alter table public.qoima_movements
    add column if not exists organization_id bigint references public.qoima_organizations (id) on delete cascade,
    add column if not exists warehouse_id bigint references public.qoima_warehouses (id) on delete restrict,
    add column if not exists to_warehouse_id bigint references public.qoima_warehouses (id) on delete restrict,
    add column if not exists document_id bigint references public.qoima_documents (id) on delete restrict,
    add column if not exists price bigint not null default 0 check (price >= 0);

alter table public.qoima_movements drop constraint if exists qoima_movements_movement_type_check;
alter table public.qoima_movements add constraint qoima_movements_movement_type_check
    check (movement_type in ('IN', 'OUT', 'ADJUST', 'TRANSFER'));
-- IN/OUT/TRANSFER are always positive; ADJUST (stocktake) is the signed difference
alter table public.qoima_movements drop constraint if exists qoima_movements_quantity_sign;
alter table public.qoima_movements add constraint qoima_movements_quantity_sign
    check (quantity <> 0 and (movement_type = 'ADJUST' or quantity > 0));

create table if not exists public.qoima_stock (
    product_id bigint not null references public.qoima_products (id) on delete cascade,
    warehouse_id bigint not null references public.qoima_warehouses (id) on delete restrict,
    organization_id bigint not null references public.qoima_organizations (id) on delete cascade,
    quantity integer not null default 0 check (quantity >= 0),
    primary key (product_id, warehouse_id)
);
create index if not exists qoima_stock_org on public.qoima_stock (organization_id);

-- ---------------------------------------------------------------- v1 → v2 data migration

do $$
declare
    v_user record;
    v_org bigint;
begin
    -- every user gets a personal organization (if they have none yet)
    for v_user in
        select u.id, u.email, p.full_name, p.company
        from auth.users u
        left join public.qoima_profiles p on p.id = u.id
        where not exists (select 1 from public.qoima_members m where m.user_id = u.id)
    loop
        insert into public.qoima_organizations (name, created_by)
        values (left(coalesce(nullif(v_user.company, ''), nullif(v_user.full_name, ''), split_part(v_user.email, '@', 1), ''), 150), v_user.id)
        returning id into v_org;
        insert into public.qoima_members (organization_id, user_id, role) values (v_org, v_user.id, 'owner');
        insert into public.qoima_profiles (id, organization_id) values (v_user.id, v_org)
        on conflict (id) do update set organization_id = coalesce(public.qoima_profiles.organization_id, excluded.organization_id),
            company = '';  -- v1 "company" became the organization name; the field now means position
    end loop;

    -- profiles without a current organization pick the first one they belong to
    update public.qoima_profiles p set organization_id = (
        select m.organization_id from public.qoima_members m where m.user_id = p.id order by m.created_at limit 1
    ) where p.organization_id is null;

    -- one default warehouse per organization
    insert into public.qoima_warehouses (organization_id, name)
    select o.id, 'Негізгі қойма' from public.qoima_organizations o
    where not exists (select 1 from public.qoima_warehouses w where w.organization_id = o.id);
end;
$$;

-- v1 rows → the owner's personal organization
update public.qoima_suppliers s set organization_id = p.organization_id
from public.qoima_profiles p where s.organization_id is null and p.id = s.owner_id;
update public.qoima_products s set organization_id = p.organization_id
from public.qoima_profiles p where s.organization_id is null and p.id = s.owner_id;
update public.qoima_movements s set organization_id = p.organization_id
from public.qoima_profiles p where s.organization_id is null and p.id = s.owner_id;

update public.qoima_movements m set warehouse_id = (
    select min(w.id) from public.qoima_warehouses w where w.organization_id = m.organization_id
) where m.warehouse_id is null;

update public.qoima_movements m set price = case when m.movement_type = 'OUT' then p.sale_price else p.purchase_price end
from public.qoima_products p where p.id = m.product_id and m.price = 0;

insert into public.qoima_stock (product_id, warehouse_id, organization_id, quantity)
select p.id, (select min(w.id) from public.qoima_warehouses w where w.organization_id = p.organization_id), p.organization_id, p.quantity
from public.qoima_products p
where p.organization_id is not null and not exists (select 1 from public.qoima_stock s where s.product_id = p.id);

-- every v1 movement becomes a one-line document so it can be printed as an invoice
do $$
declare
    v_row record;
    v_doc bigint;
begin
    for v_row in
        select m.id, m.organization_id, m.movement_type, m.warehouse_id, m.supplier_id, m.note, m.created_at, m.owner_id
        from public.qoima_movements m
        where m.document_id is null and m.organization_id is not null
        order by m.created_at, m.id
    loop
        insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, supplier_id, note, created_by, created_at)
        values (
            v_row.organization_id,
            coalesce((select max(d.number) from public.qoima_documents d
                      where d.organization_id = v_row.organization_id and d.doc_type = v_row.movement_type), 0) + 1,
            v_row.movement_type, v_row.warehouse_id, v_row.supplier_id, v_row.note, v_row.owner_id, v_row.created_at
        )
        returning id into v_doc;
        update public.qoima_movements set document_id = v_doc where id = v_row.id;
    end loop;
end;
$$;

-- orphans (no owner left) cannot be placed anywhere
delete from public.qoima_movements where organization_id is null;
delete from public.qoima_products where organization_id is null;
delete from public.qoima_suppliers where organization_id is null;

alter table public.qoima_suppliers alter column organization_id set not null;
alter table public.qoima_products alter column organization_id set not null;
alter table public.qoima_movements alter column organization_id set not null;
alter table public.qoima_movements alter column warehouse_id set not null;

drop index if exists public.qoima_suppliers_owner_name;
drop index if exists public.qoima_products_owner_sku;
drop index if exists public.qoima_movements_owner_created;
create unique index if not exists qoima_suppliers_org_name on public.qoima_suppliers (organization_id, lower(name));
create unique index if not exists qoima_products_org_sku on public.qoima_products (organization_id, lower(sku));
create index if not exists qoima_movements_org_created on public.qoima_movements (organization_id, created_at desc);
create index if not exists qoima_movements_product on public.qoima_movements (product_id);
create index if not exists qoima_movements_document on public.qoima_movements (document_id);

-- ---------------------------------------------------------------- access helpers

-- Role of the signed-in user in an organization (null = not a member).
-- SECURITY DEFINER so policies on qoima_members can use it without recursion.
create or replace function public.qoima_role(p_org bigint)
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select role from public.qoima_members where organization_id = p_org and user_id = auth.uid();
$$;

create or replace function public.qoima_current_org()
returns bigint
language sql
stable
security definer
set search_path = ''
as $$
    select p.organization_id
    from public.qoima_profiles p
    join public.qoima_members m on m.organization_id = p.organization_id and m.user_id = p.id
    where p.id = auth.uid();
$$;

alter table public.qoima_suppliers alter column organization_id set default public.qoima_current_org();
alter table public.qoima_warehouses alter column organization_id set default public.qoima_current_org();

-- Current organization + role check for RPC functions. Raises when not allowed.
create or replace function public.qoima_require_role(p_roles text[])
returns bigint
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_org bigint;
begin
    if auth.uid() is null then
        raise exception 'NOT_AUTHENTICATED';
    end if;
    v_org := public.qoima_current_org();
    if v_org is null then
        raise exception 'NO_ORGANIZATION';
    end if;
    if coalesce(public.qoima_role(v_org), '') <> all (p_roles) then
        raise exception 'FORBIDDEN';
    end if;
    return v_org;
end;
$$;

-- ---------------------------------------------------------------- row level security

alter table public.qoima_organizations enable row level security;
alter table public.qoima_members enable row level security;
alter table public.qoima_invites enable row level security;
alter table public.qoima_profiles enable row level security;
alter table public.qoima_warehouses enable row level security;
alter table public.qoima_suppliers enable row level security;
alter table public.qoima_products enable row level security;
alter table public.qoima_movements enable row level security;
alter table public.qoima_documents enable row level security;
alter table public.qoima_stock enable row level security;

-- v1 policies
drop policy if exists "own suppliers" on public.qoima_suppliers;
drop policy if exists "read own products" on public.qoima_products;
drop policy if exists "edit own products" on public.qoima_products;
drop policy if exists "read own movements" on public.qoima_movements;

drop policy if exists "members read organization" on public.qoima_organizations;
create policy "members read organization" on public.qoima_organizations
    for select to authenticated using (public.qoima_role(id) is not null);
drop policy if exists "owners edit organization" on public.qoima_organizations;
create policy "owners edit organization" on public.qoima_organizations
    for update to authenticated using (public.qoima_role(id) = 'owner') with check (public.qoima_role(id) = 'owner');

drop policy if exists "members read members" on public.qoima_members;
create policy "members read members" on public.qoima_members
    for select to authenticated using (public.qoima_role(organization_id) is not null);

drop policy if exists "owners read invites" on public.qoima_invites;
create policy "owners read invites" on public.qoima_invites
    for select to authenticated using (public.qoima_role(organization_id) = 'owner');

drop policy if exists "own profile" on public.qoima_profiles;
create policy "own profile" on public.qoima_profiles
    for all to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));

drop policy if exists "members read warehouses" on public.qoima_warehouses;
create policy "members read warehouses" on public.qoima_warehouses
    for select to authenticated using (public.qoima_role(organization_id) is not null);
drop policy if exists "owners write warehouses" on public.qoima_warehouses;
create policy "owners write warehouses" on public.qoima_warehouses
    for insert to authenticated with check (public.qoima_role(organization_id) = 'owner');
drop policy if exists "owners edit warehouses" on public.qoima_warehouses;
create policy "owners edit warehouses" on public.qoima_warehouses
    for update to authenticated using (public.qoima_role(organization_id) = 'owner')
    with check (public.qoima_role(organization_id) = 'owner');

drop policy if exists "members read suppliers" on public.qoima_suppliers;
create policy "members read suppliers" on public.qoima_suppliers
    for select to authenticated using (public.qoima_role(organization_id) is not null);
drop policy if exists "owners insert suppliers" on public.qoima_suppliers;
create policy "owners insert suppliers" on public.qoima_suppliers
    for insert to authenticated with check (public.qoima_role(organization_id) = 'owner');
drop policy if exists "owners edit suppliers" on public.qoima_suppliers;
create policy "owners edit suppliers" on public.qoima_suppliers
    for update to authenticated using (public.qoima_role(organization_id) = 'owner')
    with check (public.qoima_role(organization_id) = 'owner');
drop policy if exists "owners delete suppliers" on public.qoima_suppliers;
create policy "owners delete suppliers" on public.qoima_suppliers
    for delete to authenticated using (public.qoima_role(organization_id) = 'owner');

drop policy if exists "members read products" on public.qoima_products;
create policy "members read products" on public.qoima_products
    for select to authenticated using (public.qoima_role(organization_id) is not null);
drop policy if exists "owners edit products" on public.qoima_products;
create policy "owners edit products" on public.qoima_products
    for update to authenticated using (public.qoima_role(organization_id) = 'owner')
    with check (public.qoima_role(organization_id) = 'owner');

drop policy if exists "members read movements" on public.qoima_movements;
create policy "members read movements" on public.qoima_movements
    for select to authenticated using (public.qoima_role(organization_id) is not null);

drop policy if exists "members read documents" on public.qoima_documents;
create policy "members read documents" on public.qoima_documents
    for select to authenticated using (public.qoima_role(organization_id) is not null);

drop policy if exists "members read stock" on public.qoima_stock;
create policy "members read stock" on public.qoima_stock
    for select to authenticated using (public.qoima_role(organization_id) is not null);

-- ---------------------------------------------------------------- privileges
-- Stock, products and documents change only via RPC; plain UPDATE may touch product
-- card fields but never "quantity". Movements, documents and stock are read-only.

revoke all on public.qoima_organizations, public.qoima_members, public.qoima_invites, public.qoima_profiles,
    public.qoima_warehouses, public.qoima_suppliers, public.qoima_products, public.qoima_movements,
    public.qoima_documents, public.qoima_stock
    from anon, authenticated;

grant select on public.qoima_organizations to authenticated;
grant update (name, bin, address, phone, bank, iban, bik, director) on public.qoima_organizations to authenticated;
grant select on public.qoima_members, public.qoima_invites to authenticated;
grant select, insert, update on public.qoima_profiles to authenticated;
grant select, insert on public.qoima_warehouses to authenticated;
grant update (name, address) on public.qoima_warehouses to authenticated;
grant select, insert, update, delete on public.qoima_suppliers to authenticated;
grant select on public.qoima_products to authenticated;
grant update (name, sku, category, unit, min_quantity, purchase_price, sale_price, description, is_active, photo_path, updated_at)
    on public.qoima_products to authenticated;
grant select on public.qoima_movements, public.qoima_documents, public.qoima_stock to authenticated;

-- ---------------------------------------------------------------- new user → profile + organization

create or replace function public.qoima_handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_language text := coalesce(new.raw_user_meta_data ->> 'language', 'kk');
    v_name text := left(coalesce(new.raw_user_meta_data ->> 'full_name', ''), 120);
    v_company text := left(coalesce(new.raw_user_meta_data ->> 'company', ''), 120);
    v_org bigint;
begin
    if v_language not in ('kk', 'ru', 'en') then
        v_language := 'kk';
    end if;
    insert into public.qoima_organizations (name, created_by)
    values (left(coalesce(nullif(v_company, ''), nullif(v_name, ''), split_part(new.email, '@', 1), ''), 150), new.id)
    returning id into v_org;
    insert into public.qoima_members (organization_id, user_id, role) values (v_org, new.id, 'owner');
    insert into public.qoima_warehouses (organization_id, name)
    values (v_org, case v_language when 'ru' then 'Основной склад' when 'en' then 'Main warehouse' else 'Негізгі қойма' end);
    -- profile.company is the person's position; the organization name lives in qoima_organizations
    insert into public.qoima_profiles (id, full_name, language, organization_id)
    values (new.id, v_name, v_language, v_org)
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
-- (Also switch off Authentication → Sign In / Providers → Email → "Confirm email".)

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

update auth.users set email_confirmed_at = now() where email_confirmed_at is null;

-- ---------------------------------------------------------------- internal: change stock

-- Adds p_delta to one warehouse and to the product total; returns the new total.
create or replace function public.qoima_apply_stock(p_org bigint, p_product bigint, p_warehouse bigint, p_delta integer)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_left integer;
    v_total integer;
begin
    insert into public.qoima_stock (product_id, warehouse_id, organization_id, quantity)
    values (p_product, p_warehouse, p_org, 0)
    on conflict (product_id, warehouse_id) do nothing;

    select quantity + p_delta into v_left from public.qoima_stock
    where product_id = p_product and warehouse_id = p_warehouse
    for update;
    if v_left < 0 then
        raise exception 'INSUFFICIENT_STOCK';
    end if;
    update public.qoima_stock set quantity = v_left where product_id = p_product and warehouse_id = p_warehouse;

    update public.qoima_products set quantity = quantity + p_delta, updated_at = now()
    where id = p_product
    returning quantity into v_total;
    return v_total;
end;
$$;

create or replace function public.qoima_next_number(p_org bigint, p_type text)
returns integer
language sql
security definer
set search_path = ''
as $$
    select coalesce(max(number), 0) + 1 from public.qoima_documents where organization_id = p_org and doc_type = p_type;
$$;

-- ---------------------------------------------------------------- RPC: create product

drop function if exists public.qoima_create_product(text, text, text, text, integer, bigint, bigint, text, integer, text);

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
    p_note text default '',
    p_warehouse_id bigint default null
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner']);
    v_id bigint;
    v_warehouse bigint;
    v_doc bigint;
begin
    if p_initial_quantity is null or p_initial_quantity < 0 then
        raise exception 'INVALID_QUANTITY';
    end if;
    select id into v_warehouse from public.qoima_warehouses
    where organization_id = v_org and (p_warehouse_id is null or id = p_warehouse_id)
    order by id limit 1;
    if v_warehouse is null then
        raise exception 'NOT_FOUND';
    end if;

    insert into public.qoima_products
        (organization_id, name, sku, category, unit, min_quantity, purchase_price, sale_price, description, quantity)
    values
        (v_org, btrim(p_name), btrim(p_sku), coalesce(btrim(p_category), ''),
         coalesce(nullif(btrim(p_unit), ''), 'дана'), coalesce(p_min_quantity, 0),
         coalesce(p_purchase_price, 0), coalesce(p_sale_price, 0), coalesce(p_description, ''), 0)
    returning id into v_id;

    insert into public.qoima_stock (product_id, warehouse_id, organization_id, quantity) values (v_id, v_warehouse, v_org, 0);

    if p_initial_quantity > 0 then
        perform 1 from public.qoima_organizations where id = v_org for update;
        insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, note)
        values (v_org, public.qoima_next_number(v_org, 'IN'), 'IN', v_warehouse, coalesce(p_note, ''))
        returning id into v_doc;
        insert into public.qoima_movements
            (organization_id, product_id, movement_type, quantity, balance_after, warehouse_id, document_id, price, note)
        values (v_org, v_id, 'IN', p_initial_quantity,
                public.qoima_apply_stock(v_org, v_id, v_warehouse, p_initial_quantity),
                v_warehouse, v_doc, coalesce(p_purchase_price, 0), coalesce(p_note, ''));
    end if;

    return v_id;
end;
$$;

-- ---------------------------------------------------------------- RPC: document (receipt / issue / transfer)
-- p_items: [{"product_id": 1, "quantity": 5}, ...]. All lines succeed or none do.

drop function if exists public.qoima_register_movement(bigint, text, integer, text, bigint);

create or replace function public.qoima_register_document(
    p_type text,
    p_warehouse_id bigint,
    p_items jsonb,
    p_note text default '',
    p_supplier_id bigint default null,
    p_to_warehouse_id bigint default null,
    p_counterparty text default ''
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner', 'storekeeper']);
    v_doc bigint;
    v_item jsonb;
    v_product public.qoima_products;
    v_quantity integer;
    v_total integer;
begin
    if p_type not in ('IN', 'OUT', 'TRANSFER') then
        raise exception 'INVALID_TYPE';
    end if;
    if jsonb_typeof(p_items) is distinct from 'array' or jsonb_array_length(p_items) = 0 then
        raise exception 'INVALID_INPUT';
    end if;
    if not exists (select 1 from public.qoima_warehouses where id = p_warehouse_id and organization_id = v_org) then
        raise exception 'NOT_FOUND';
    end if;
    if p_type = 'TRANSFER' and (
        p_to_warehouse_id is null or p_to_warehouse_id = p_warehouse_id
        or not exists (select 1 from public.qoima_warehouses where id = p_to_warehouse_id and organization_id = v_org)
    ) then
        raise exception 'INVALID_TRANSFER';
    end if;
    if p_type = 'IN' and p_supplier_id is not null and not exists (
        select 1 from public.qoima_suppliers where id = p_supplier_id and organization_id = v_org
    ) then
        raise exception 'NOT_FOUND';
    end if;

    -- serialize numbering inside the organization
    perform 1 from public.qoima_organizations where id = v_org for update;
    insert into public.qoima_documents
        (organization_id, number, doc_type, warehouse_id, to_warehouse_id, supplier_id, counterparty, note)
    values (v_org, public.qoima_next_number(v_org, p_type), p_type, p_warehouse_id,
            case when p_type = 'TRANSFER' then p_to_warehouse_id end,
            case when p_type = 'IN' then p_supplier_id end,
            left(coalesce(btrim(p_counterparty), ''), 150), left(coalesce(p_note, ''), 200))
    returning id into v_doc;

    for v_item in select value from jsonb_array_elements(p_items) loop
        v_quantity := (v_item ->> 'quantity')::integer;
        if v_quantity is null or v_quantity <= 0 then
            raise exception 'INVALID_QUANTITY';
        end if;

        -- lock the row so two simultaneous issues cannot both pass the check
        select * into v_product from public.qoima_products
        where id = (v_item ->> 'product_id')::bigint and organization_id = v_org
        for update;
        if not found then
            raise exception 'NOT_FOUND';
        end if;
        if not v_product.is_active then
            raise exception 'PRODUCT_INACTIVE';
        end if;

        if p_type = 'IN' then
            v_total := public.qoima_apply_stock(v_org, v_product.id, p_warehouse_id, v_quantity);
        elsif p_type = 'OUT' then
            v_total := public.qoima_apply_stock(v_org, v_product.id, p_warehouse_id, -v_quantity);
        else
            perform public.qoima_apply_stock(v_org, v_product.id, p_warehouse_id, -v_quantity);
            v_total := public.qoima_apply_stock(v_org, v_product.id, p_to_warehouse_id, v_quantity);
        end if;

        insert into public.qoima_movements
            (organization_id, product_id, movement_type, quantity, balance_after, warehouse_id, to_warehouse_id,
             supplier_id, document_id, price, note)
        values (v_org, v_product.id, p_type, v_quantity, v_total, p_warehouse_id,
                case when p_type = 'TRANSFER' then p_to_warehouse_id end,
                case when p_type = 'IN' then p_supplier_id end, v_doc,
                case when p_type = 'OUT' then v_product.sale_price else v_product.purchase_price end,
                left(coalesce(p_note, ''), 200));
    end loop;

    return v_doc;
end;
$$;

-- ---------------------------------------------------------------- RPC: stocktake (inventory count in one warehouse)

drop function if exists public.qoima_stocktake(jsonb, text);

create or replace function public.qoima_stocktake(p_warehouse_id bigint, p_items jsonb, p_note text default '')
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner', 'storekeeper']);
    v_item jsonb;
    v_product public.qoima_products;
    v_counted integer;
    v_current integer;
    v_changed integer := 0;
    v_doc bigint;
    v_total integer;
begin
    if jsonb_typeof(p_items) is distinct from 'array' then
        raise exception 'INVALID_INPUT';
    end if;
    if not exists (select 1 from public.qoima_warehouses where id = p_warehouse_id and organization_id = v_org) then
        raise exception 'NOT_FOUND';
    end if;

    for v_item in select value from jsonb_array_elements(p_items) loop
        v_counted := (v_item ->> 'counted')::integer;
        if v_counted is null or v_counted < 0 then
            raise exception 'INVALID_QUANTITY';
        end if;

        select * into v_product from public.qoima_products
        where id = (v_item ->> 'product_id')::bigint and organization_id = v_org
        for update;
        if not found then
            raise exception 'NOT_FOUND';
        end if;

        select coalesce((select quantity from public.qoima_stock
                         where product_id = v_product.id and warehouse_id = p_warehouse_id), 0)
        into v_current;

        if v_counted <> v_current then
            if v_doc is null then
                perform 1 from public.qoima_organizations where id = v_org for update;
                insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, note)
                values (v_org, public.qoima_next_number(v_org, 'ADJUST'), 'ADJUST', p_warehouse_id, left(coalesce(p_note, ''), 200))
                returning id into v_doc;
            end if;
            v_total := public.qoima_apply_stock(v_org, v_product.id, p_warehouse_id, v_counted - v_current);
            insert into public.qoima_movements
                (organization_id, product_id, movement_type, quantity, balance_after, warehouse_id, document_id, price, note)
            values (v_org, v_product.id, 'ADJUST', v_counted - v_current, v_total, p_warehouse_id, v_doc,
                    v_product.purchase_price, left(coalesce(p_note, ''), 200));
            v_changed := v_changed + 1;
        end if;
    end loop;

    return v_changed;
end;
$$;

-- ---------------------------------------------------------------- RPC: warehouses

create or replace function public.qoima_delete_warehouse(p_warehouse_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner']);
begin
    if not exists (select 1 from public.qoima_warehouses where id = p_warehouse_id and organization_id = v_org) then
        raise exception 'NOT_FOUND';
    end if;
    if (select count(*) from public.qoima_warehouses where organization_id = v_org) <= 1 then
        raise exception 'LAST_WAREHOUSE';
    end if;
    if exists (select 1 from public.qoima_stock where warehouse_id = p_warehouse_id and quantity > 0) then
        raise exception 'WAREHOUSE_NOT_EMPTY';
    end if;
    delete from public.qoima_stock where warehouse_id = p_warehouse_id;
    delete from public.qoima_warehouses where id = p_warehouse_id;  -- history keeps it alive (FK restrict → 23503)
end;
$$;

-- ---------------------------------------------------------------- RPC: team

create or replace function public.qoima_my_organizations()
returns table (id bigint, name text, role text, is_current boolean)
language sql
stable
security definer
set search_path = ''
as $$
    select o.id, o.name, m.role, o.id = p.organization_id
    from public.qoima_members m
    join public.qoima_organizations o on o.id = m.organization_id
    left join public.qoima_profiles p on p.id = m.user_id
    where m.user_id = auth.uid()
    order by o.name;
$$;

create or replace function public.qoima_team()
returns table (user_id uuid, email text, full_name text, role text, joined_at timestamptz)
language sql
stable
security definer
set search_path = ''
as $$
    select m.user_id, u.email::text, coalesce(p.full_name, ''), m.role, m.created_at
    from public.qoima_members m
    join auth.users u on u.id = m.user_id
    left join public.qoima_profiles p on p.id = m.user_id
    where m.organization_id = public.qoima_current_org()
      and public.qoima_role(m.organization_id) is not null
    order by m.created_at;
$$;

create or replace function public.qoima_switch_organization(p_org bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if public.qoima_role(p_org) is null then
        raise exception 'FORBIDDEN';
    end if;
    update public.qoima_profiles set organization_id = p_org, updated_at = now() where id = auth.uid();
end;
$$;

create or replace function public.qoima_create_invite(p_email text, p_role text)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner']);
    v_token text;
begin
    if p_role not in ('owner', 'storekeeper', 'accountant') then
        raise exception 'INVALID_INPUT';
    end if;
    if exists (
        select 1 from public.qoima_members m join auth.users u on u.id = m.user_id
        where m.organization_id = v_org and lower(u.email) = lower(btrim(p_email))
    ) then
        raise exception 'ALREADY_MEMBER';
    end if;
    delete from public.qoima_invites
    where organization_id = v_org and lower(email) = lower(btrim(p_email)) and accepted_at is null;
    insert into public.qoima_invites (organization_id, email, role)
    values (v_org, lower(btrim(p_email)), p_role)
    returning token into v_token;
    return v_token;
end;
$$;

create or replace function public.qoima_cancel_invite(p_invite_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner']);
begin
    delete from public.qoima_invites where id = p_invite_id and organization_id = v_org and accepted_at is null;
end;
$$;

-- Invite preview for the acceptance page: organization name and role, only for the invited email.
create or replace function public.qoima_invite_info(p_token text)
returns table (organization_name text, role text, email text, matches boolean)
language sql
stable
security definer
set search_path = ''
as $$
    select o.name, i.role, i.email, lower(i.email) = lower(coalesce(auth.jwt() ->> 'email', ''))
    from public.qoima_invites i
    join public.qoima_organizations o on o.id = i.organization_id
    where i.token = p_token and i.accepted_at is null;
$$;

create or replace function public.qoima_accept_invite(p_token text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_invite public.qoima_invites;
begin
    if auth.uid() is null then
        raise exception 'NOT_AUTHENTICATED';
    end if;
    select * into v_invite from public.qoima_invites where token = p_token and accepted_at is null for update;
    if not found then
        raise exception 'NOT_FOUND';
    end if;
    if lower(v_invite.email) <> lower(coalesce(auth.jwt() ->> 'email', '')) then
        raise exception 'INVITE_EMAIL_MISMATCH';
    end if;
    insert into public.qoima_members (organization_id, user_id, role)
    values (v_invite.organization_id, auth.uid(), v_invite.role)
    on conflict (organization_id, user_id) do update set role = excluded.role;
    update public.qoima_invites set accepted_at = now() where id = v_invite.id;
    update public.qoima_profiles set organization_id = v_invite.organization_id, updated_at = now() where id = auth.uid();
    return v_invite.organization_id;
end;
$$;

create or replace function public.qoima_set_member_role(p_user_id uuid, p_role text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_require_role(array['owner']);
begin
    if p_role not in ('owner', 'storekeeper', 'accountant') then
        raise exception 'INVALID_INPUT';
    end if;
    if p_role <> 'owner' and (select role from public.qoima_members where organization_id = v_org and user_id = p_user_id) = 'owner'
       and (select count(*) from public.qoima_members where organization_id = v_org and role = 'owner') <= 1 then
        raise exception 'LAST_OWNER';
    end if;
    update public.qoima_members set role = p_role where organization_id = v_org and user_id = p_user_id;
end;
$$;

create or replace function public.qoima_remove_member(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_org bigint := public.qoima_current_org();
begin
    -- owners remove anyone; any member may leave by removing themselves
    if v_org is null or (public.qoima_role(v_org) <> 'owner' and p_user_id <> auth.uid()) then
        raise exception 'FORBIDDEN';
    end if;
    if (select role from public.qoima_members where organization_id = v_org and user_id = p_user_id) = 'owner'
       and (select count(*) from public.qoima_members where organization_id = v_org and role = 'owner') <= 1 then
        raise exception 'LAST_OWNER';
    end if;
    delete from public.qoima_members where organization_id = v_org and user_id = p_user_id;
    update public.qoima_profiles p set organization_id = (
        select m.organization_id from public.qoima_members m where m.user_id = p.id order by m.created_at limit 1
    ) where p.id = p_user_id;
end;
$$;

-- ---------------------------------------------------------------- notifications (daily low-stock digest)
-- The site's cron endpoint calls qoima_low_stock_digest with a shared secret. The secret lives in a
-- private schema that the API cannot read. Copy it into the CRON_SECRET environment variable:
--     select value from qoima_private.settings where key = 'cron_secret';

create schema if not exists qoima_private;
revoke all on schema qoima_private from public, anon, authenticated;
create table if not exists qoima_private.settings (key text primary key, value text not null);
insert into qoima_private.settings (key, value)
values ('cron_secret', replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', ''))
on conflict (key) do nothing;

create or replace function public.qoima_low_stock_digest(p_secret text)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    if p_secret is null or p_secret <> (select value from qoima_private.settings where key = 'cron_secret') then
        raise exception 'FORBIDDEN';
    end if;
    select coalesce(jsonb_agg(row_data), '[]'::jsonb) into v_result from (
        select jsonb_build_object(
            'chat_id', p.telegram_chat_id,
            'notify_telegram', p.notify_telegram,
            'email', case when p.notify_email then u.email else null end,
            'language', p.language,
            'organization', o.name,
            'items', (
                select coalesce(jsonb_agg(jsonb_build_object(
                    'name', pr.name, 'sku', pr.sku, 'unit', pr.unit,
                    'quantity', pr.quantity, 'min_quantity', pr.min_quantity,
                    'out_30', coalesce((select sum(mv.quantity) from public.qoima_movements mv
                                        where mv.product_id = pr.id and mv.movement_type = 'OUT'
                                          and mv.created_at > now() - interval '30 days'), 0)
                ) order by pr.quantity - pr.min_quantity, pr.name), '[]'::jsonb)
                from public.qoima_products pr
                where pr.organization_id = o.id and pr.is_active and pr.quantity <= pr.min_quantity
            )
        ) as row_data
        from public.qoima_profiles p
        join auth.users u on u.id = p.id
        join public.qoima_organizations o on o.id = p.organization_id
        join public.qoima_members m on m.organization_id = o.id and m.user_id = p.id
        where (p.telegram_chat_id is not null and p.notify_telegram) or p.notify_email
    ) digest
    where jsonb_array_length(row_data -> 'items') > 0;
    return v_result;
end;
$$;

-- ---------------------------------------------------------------- product photos (Supabase Storage)
-- Public bucket: images are readable by URL; only owners of the organization (first folder
-- of the path) may upload or delete them. Path: <organization_id>/<product_id>-<random>.<ext>

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('qoima-photos', 'qoima-photos', true, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update set public = true, file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "qoima photos read" on storage.objects;
create policy "qoima photos read" on storage.objects
    for select to authenticated using (bucket_id = 'qoima-photos');
drop policy if exists "qoima photos insert" on storage.objects;
create policy "qoima photos insert" on storage.objects
    for insert to authenticated with check (
        bucket_id = 'qoima-photos'
        and (storage.foldername(name))[1] in (
            select organization_id::text from public.qoima_members where user_id = auth.uid() and role = 'owner')
    );
drop policy if exists "qoima photos update" on storage.objects;
create policy "qoima photos update" on storage.objects
    for update to authenticated using (
        bucket_id = 'qoima-photos'
        and (storage.foldername(name))[1] in (
            select organization_id::text from public.qoima_members where user_id = auth.uid() and role = 'owner')
    );
drop policy if exists "qoima photos delete" on storage.objects;
create policy "qoima photos delete" on storage.objects
    for delete to authenticated using (
        bucket_id = 'qoima-photos'
        and (storage.foldername(name))[1] in (
            select organization_id::text from public.qoima_members where user_id = auth.uid() and role = 'owner')
    );

-- ---------------------------------------------------------------- function privileges

revoke all on function public.qoima_handle_new_user() from public, anon, authenticated;
revoke all on function public.qoima_autoconfirm_user() from public, anon, authenticated;
revoke all on function public.qoima_apply_stock(bigint, bigint, bigint, integer) from public, anon, authenticated;
revoke all on function public.qoima_next_number(bigint, text) from public, anon, authenticated;
revoke all on function public.qoima_require_role(text[]) from public, anon, authenticated;

revoke all on function public.qoima_role(bigint) from public, anon;
revoke all on function public.qoima_current_org() from public, anon;
revoke all on function public.qoima_create_product(text, text, text, text, integer, bigint, bigint, text, integer, text, bigint) from public, anon;
revoke all on function public.qoima_register_document(text, bigint, jsonb, text, bigint, bigint, text) from public, anon;
revoke all on function public.qoima_stocktake(bigint, jsonb, text) from public, anon;
revoke all on function public.qoima_delete_warehouse(bigint) from public, anon;
revoke all on function public.qoima_my_organizations() from public, anon;
revoke all on function public.qoima_team() from public, anon;
revoke all on function public.qoima_switch_organization(bigint) from public, anon;
revoke all on function public.qoima_create_invite(text, text) from public, anon;
revoke all on function public.qoima_cancel_invite(bigint) from public, anon;
revoke all on function public.qoima_invite_info(text) from public, anon;
revoke all on function public.qoima_accept_invite(text) from public, anon;
revoke all on function public.qoima_set_member_role(uuid, text) from public, anon;
revoke all on function public.qoima_remove_member(uuid) from public, anon;
revoke all on function public.qoima_low_stock_digest(text) from public, authenticated;

grant execute on function public.qoima_role(bigint) to authenticated;
grant execute on function public.qoima_current_org() to authenticated;
grant execute on function public.qoima_create_product(text, text, text, text, integer, bigint, bigint, text, integer, text, bigint) to authenticated;
grant execute on function public.qoima_register_document(text, bigint, jsonb, text, bigint, bigint, text) to authenticated;
grant execute on function public.qoima_stocktake(bigint, jsonb, text) to authenticated;
grant execute on function public.qoima_delete_warehouse(bigint) to authenticated;
grant execute on function public.qoima_my_organizations() to authenticated;
grant execute on function public.qoima_team() to authenticated;
grant execute on function public.qoima_switch_organization(bigint) to authenticated;
grant execute on function public.qoima_create_invite(text, text) to authenticated;
grant execute on function public.qoima_cancel_invite(bigint) to authenticated;
grant execute on function public.qoima_invite_info(text) to authenticated;
grant execute on function public.qoima_accept_invite(text) to authenticated;
grant execute on function public.qoima_set_member_role(uuid, text) to authenticated;
grant execute on function public.qoima_remove_member(uuid) to authenticated;
grant execute on function public.qoima_low_stock_digest(text) to anon;

notify pgrst, 'reload schema';
