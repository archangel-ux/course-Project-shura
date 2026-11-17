-- Demo account with ready-made data: 3 warehouses, 4 suppliers, 18 products and two months of history
-- (receipts, issues, transfers, a stocktake). Several products end below the minimum, so the
-- dashboard, forecast and the Telegram digest have something to show.
--
-- Run in Supabase → SQL Editor after schema.sql. Safe to re-run: every run wipes the demo
-- organization and fills it again (a linked Telegram chat is kept).
--
--     email:    demo@qoima.kz
--     password: Demo2026!

do $$
declare
    c_email    constant text := 'demo@qoima.kz';
    c_password constant text := 'Demo2026!';
    v_uid uuid;
    v_org bigint;
    w_main bigint;
    w_shop bigint;
    w_north bigint;
    v_sup bigint[];
    v_now timestamptz := now();
    v_today date := (now() at time zone 'Asia/Almaty')::date;
    v_day integer;
    v_base timestamptz;
    v_doc bigint;
    v_id bigint;
    v_qty integer;
    v_cur integer;
    v_total integer;
    v_counted integer;
    v_p record;
    n_in integer := 0;
    n_out integer := 0;
    n_tr integer := 0;
    n_adj integer := 0;
    v_clients text[] := array['ТОО «Арна Логистик»', 'ИП Нурланов', 'Офис на Сатпаева', 'ТОО «Береке Строй»',
                              'Бухгалтерия', 'ИП Абенова', 'ТОО «Самал Сервис»', 'Отдел продаж'];
begin
    perform setseed(0.2026);

    -- ------------------------------------------------------------ account
    select id into v_uid from auth.users where lower(email) = c_email;
    if v_uid is null then
        v_uid := gen_random_uuid();
        insert into auth.users (
            instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
            raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
            confirmation_token, recovery_token, email_change_token_new, email_change
        ) values (
            '00000000-0000-0000-0000-000000000000', v_uid, 'authenticated', 'authenticated', c_email,
            extensions.crypt(c_password, extensions.gen_salt('bf')), v_now,
            '{"provider": "email", "providers": ["email"]}',
            '{"full_name": "Арман Касымов", "company": "ТОО «Алем Снаб»", "language": "ru"}',
            v_now, v_now, '', '', '', ''
        );
        insert into auth.identities (id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
        values (gen_random_uuid(), v_uid, v_uid::text,
                jsonb_build_object('sub', v_uid::text, 'email', c_email, 'email_verified', true),
                'email', v_now, v_now, v_now);
    else
        update auth.users set encrypted_password = extensions.crypt(c_password, extensions.gen_salt('bf')),
                              email_confirmed_at = coalesce(email_confirmed_at, v_now)
        where id = v_uid;
    end if;

    -- the sign-up trigger made a profile + organization; recreate them if they are missing
    select m.organization_id into v_org from public.qoima_members m
    where m.user_id = v_uid and m.role = 'owner' order by m.created_at limit 1;
    if v_org is null then
        insert into public.qoima_organizations (name, created_by) values ('ТОО «Алем Снаб»', v_uid) returning id into v_org;
        insert into public.qoima_members (organization_id, user_id, role) values (v_org, v_uid, 'owner');
    end if;
    insert into public.qoima_profiles (id, organization_id) values (v_uid, v_org) on conflict (id) do nothing;
    update public.qoima_profiles
    set full_name = 'Арман Касымов', company = 'Директор', phone = '+7 701 000 00 00',
        language = 'ru', organization_id = v_org, updated_at = v_now
    where id = v_uid;

    -- ------------------------------------------------------------ wipe the demo organization
    delete from public.qoima_movements where organization_id = v_org;
    delete from public.qoima_documents where organization_id = v_org;
    delete from public.qoima_stock where organization_id = v_org;
    delete from public.qoima_products where organization_id = v_org;
    delete from public.qoima_suppliers where organization_id = v_org;
    delete from public.qoima_warehouses where organization_id = v_org;
    delete from public.qoima_invites where organization_id = v_org;
    delete from public.qoima_members where organization_id = v_org and user_id <> v_uid;

    update public.qoima_organizations set
        name = 'ТОО «Алем Снаб»', bin = '190340021547', address = 'г. Алматы, пр. Абая, 150, офис 12',
        phone = '+7 727 300 00 00', bank = 'АО «Алатау Банк»', iban = 'KZ12 3456 7890 1234 5678',
        bik = 'ALATKZKA', director = 'Касымов А. Б.'
    where id = v_org;

    -- ------------------------------------------------------------ warehouses & suppliers
    insert into public.qoima_warehouses (organization_id, name, address, created_at)
    values (v_org, 'Основной склад', 'г. Алматы, ул. Рыскулова, 57', v_now - interval '62 days') returning id into w_main;
    insert into public.qoima_warehouses (organization_id, name, address, created_at)
    values (v_org, 'Магазин на Абая', 'г. Алматы, пр. Абая, 150', v_now - interval '62 days') returning id into w_shop;
    insert into public.qoima_warehouses (organization_id, name, address, created_at)
    values (v_org, 'Склад «Север»', 'г. Алматы, ул. Бурундайская, 9', v_now - interval '40 days') returning id into w_north;

    with s as (
        insert into public.qoima_suppliers (organization_id, name, contact_person, phone, email, note, created_at)
        values
            (v_org, 'ТОО «КанцОпт Алматы»', 'Динара Ахметова', '+7 707 111 22 33', 'sales@kancopt.example', 'Доставка по вторникам', v_now - interval '62 days'),
            (v_org, 'ТОО «ТехноСнаб»', 'Ерлан Жумабаев', '+7 701 222 33 44', 'order@technosnab.example', 'Оргтехника и электротовары', v_now - interval '62 days'),
            (v_org, 'ИП «Чистый дом»', 'Гульнара Серикова', '+7 777 333 44 55', '', 'Хозтовары, оплата по факту', v_now - interval '62 days'),
            (v_org, 'ТОО «Аква Сервис»', 'Максат Оспанов', '+7 708 444 55 66', 'aqua@service.example', '', v_now - interval '62 days')
        returning id
    )
    select array_agg(id order by id) into v_sup from s;

    -- ------------------------------------------------------------ products
    -- rate = average issue per day; starve = no restocks, ends low (final = expected balance today)
    create temporary table demo_items (
        id bigint, sku text, name text, category text, unit text, min_q integer, buy bigint, sell bigint,
        rate numeric, sup integer, to_shop boolean, starve boolean, final_q integer
    ) on commit drop;
    insert into demo_items (sku, name, category, unit, min_q, buy, sell, rate, sup, to_shop, starve, final_q) values
        ('PAP-A4-500', 'Бумага офисная A4, 500 листов', 'Канцелярия', 'пачка', 40, 2100, 2900, 6, 1, true, false, null),
        ('PEN-BL-01', 'Ручка шариковая синяя', 'Канцелярия', 'шт', 100, 60, 120, 14, 1, true, false, null),
        ('STP-246', 'Степлер №24/6', 'Канцелярия', 'шт', 10, 1500, 2600, 0.6, 1, true, false, null),
        ('STP-SC-1000', 'Скобы №24/6, 1000 шт', 'Канцелярия', 'упак', 30, 180, 350, 3, 1, true, false, null),
        ('FLD-75', 'Папка-регистратор 75 мм', 'Канцелярия', 'шт', 25, 900, 1600, 2, 1, false, true, 9),
        ('MRK-BK', 'Маркер перманентный чёрный', 'Канцелярия', 'шт', 30, 250, 490, 2.5, 1, true, false, null),
        ('CRT-85A', 'Картридж для лазерного принтера 85A', 'Оргтехника', 'шт', 8, 9500, 15500, 0.5, 2, false, true, -5),
        ('MSE-WL-02', 'Мышь беспроводная', 'Оргтехника', 'шт', 6, 3200, 5900, 0.4, 2, false, false, null),
        ('KBD-USB-01', 'Клавиатура USB', 'Оргтехника', 'шт', 5, 4100, 7500, 0.3, 2, false, false, null),
        ('EXT-5-3', 'Удлинитель на 5 розеток, 3 м', 'Электротовары', 'шт', 8, 2800, 4900, 0.5, 2, false, false, null),
        ('BAT-AA-4', 'Батарейки AA, 4 шт', 'Электротовары', 'упак', 40, 650, 1200, 4, 2, true, true, 14),
        ('LED-E27-10', 'Лампа светодиодная E27, 10 Вт', 'Электротовары', 'шт', 30, 450, 890, 2, 2, false, false, null),
        ('TWL-2R', 'Бумажные полотенца, 2 рулона', 'Хозтовары', 'упак', 30, 700, 1300, 3, 3, true, false, null),
        ('SOAP-5L', 'Мыло жидкое, 5 л', 'Хозтовары', 'шт', 6, 3600, 5800, 0.4, 3, false, false, null),
        ('BAG-120', 'Пакеты для мусора 120 л, 10 шт', 'Хозтовары', 'упак', 20, 900, 1700, 1.5, 3, true, false, null),
        ('WAT-19', 'Вода питьевая, 19 л', 'Продукты', 'шт', 15, 1100, 1800, 3, 4, false, false, null),
        ('COF-1KG', 'Кофе молотый, 1 кг', 'Продукты', 'кг', 5, 7800, 11900, 0.3, 4, true, false, null),
        ('SUG-1KG', 'Сахар-рафинад, 1 кг', 'Продукты', 'кг', 10, 650, 950, 0.7, 4, false, true, 4);

    for v_p in select * from demo_items order by sku loop
        insert into public.qoima_products
            (organization_id, owner_id, name, sku, category, unit, min_quantity, purchase_price, sale_price,
             description, quantity, created_at, updated_at)
        values (v_org, v_uid, v_p.name, v_p.sku, v_p.category, v_p.unit, v_p.min_q, v_p.buy * 100, v_p.sell * 100,
                '', 0, v_now - interval '60 days', v_now - interval '60 days')
        returning id into v_id;
        update demo_items set id = v_id where sku = v_p.sku;
    end loop;

    -- ------------------------------------------------------------ two months of operations
    for v_day in reverse 60..0 loop
        -- 09:00 Almaty on that day; today the events are placed in the last few hours
        v_base := case when v_day = 0 then v_now - interval '6 hours'
                       else ((v_today - v_day) + time '09:00') at time zone 'Asia/Almaty' end;

        -- receipts: the opening stock on day 60, then each supplier delivers once a week
        for v_sup_idx in 1..4 loop
            continue when not (v_day = 60 or (v_day < 60 and v_day % 7 = v_sup_idx));
            v_doc := null;
            for v_p in select d.*, coalesce((select quantity from public.qoima_stock s
                                             where s.product_id = d.id and s.warehouse_id = w_main), 0) as main_q
                       from demo_items d where d.sup = v_sup_idx order by d.sku loop
                if v_day = 60 then
                    v_qty := case when v_p.starve then ceil(v_p.rate * 51) + v_p.final_q
                                  else ceil(v_p.rate * 21) + v_p.min_q * 2 end;
                elsif not v_p.starve and v_p.main_q < v_p.min_q + ceil(v_p.rate * 12) then
                    v_qty := (ceil((v_p.rate * 21 + v_p.min_q) / 5.0) * 5)::integer;
                else
                    continue;
                end if;
                if v_doc is null then
                    n_in := n_in + 1;
                    insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, supplier_id, note, created_by, created_at)
                    values (v_org, n_in, 'IN', w_main, v_sup[v_sup_idx],
                            case when v_day = 60 then 'Начальные остатки' else 'Счёт-фактура № ' || (1000 + n_in * 7) end,
                            v_uid, v_base + interval '1 hour' + v_sup_idx * interval '7 minutes')
                    returning id into v_doc;
                end if;
                v_total := public.qoima_apply_stock(v_org, v_p.id, w_main, v_qty);
                insert into public.qoima_movements (organization_id, owner_id, product_id, movement_type, quantity, balance_after,
                                                    warehouse_id, supplier_id, document_id, price, note, created_at)
                select v_org, v_uid, v_p.id, 'IN', v_qty, v_total, w_main, v_sup[v_sup_idx], v_doc, v_p.buy * 100, d.note, d.created_at
                from public.qoima_documents d where d.id = v_doc;
            end loop;
        end loop;

        -- transfers to the shop every 10 days, and one batch to the north warehouse
        if v_day % 10 = 5 or v_day = 38 then
            v_doc := null;
            for v_p in select d.*, coalesce((select quantity from public.qoima_stock s
                                             where s.product_id = d.id and s.warehouse_id = w_main), 0) as main_q
                       from demo_items d
                       where (v_day = 38 and d.category in ('Оргтехника', 'Электротовары') and not d.starve)
                          or (v_day <> 38 and d.to_shop)
                       order by d.sku loop
                v_qty := greatest(2, ceil(v_p.rate * case when v_day = 38 then 4 else 3 end))::integer;
                continue when v_p.main_q < v_qty * 2;
                if v_doc is null then
                    n_tr := n_tr + 1;
                    insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, to_warehouse_id, note, created_by, created_at)
                    values (v_org, n_tr, 'TRANSFER', w_main, case when v_day = 38 then w_north else w_shop end,
                            case when v_day = 38 then 'Открытие склада «Север»' else 'Пополнение витрины' end,
                            v_uid, v_base + interval '3 hours')
                    returning id into v_doc;
                end if;
                perform public.qoima_apply_stock(v_org, v_p.id, w_main, -v_qty);
                v_total := public.qoima_apply_stock(v_org, v_p.id, case when v_day = 38 then w_north else w_shop end, v_qty);
                insert into public.qoima_movements (organization_id, owner_id, product_id, movement_type, quantity, balance_after,
                                                    warehouse_id, to_warehouse_id, document_id, price, note, created_at)
                select v_org, v_uid, v_p.id, 'TRANSFER', v_qty, v_total, w_main, d.to_warehouse_id, v_doc, v_p.buy * 100, d.note, d.created_at
                from public.qoima_documents d where d.id = v_doc;
            end loop;
        end if;

        -- stocktake two weeks ago: a couple of discrepancies in the main warehouse
        if v_day = 14 then
            v_doc := null;
            for v_p in select d.*, s.quantity as main_q from demo_items d
                       join public.qoima_stock s on s.product_id = d.id and s.warehouse_id = w_main
                       where d.sku in ('PEN-BL-01', 'MRK-BK', 'TWL-2R') order by d.sku loop
                v_counted := greatest(0, v_p.main_q + case v_p.sku when 'PEN-BL-01' then -6 when 'MRK-BK' then -2 else 1 end);
                continue when v_counted = v_p.main_q;
                if v_doc is null then
                    n_adj := n_adj + 1;
                    insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, note, created_by, created_at)
                    values (v_org, n_adj, 'ADJUST', w_main, 'Плановая инвентаризация', v_uid, v_base + interval '2 hours')
                    returning id into v_doc;
                end if;
                v_total := public.qoima_apply_stock(v_org, v_p.id, w_main, v_counted - v_p.main_q);
                insert into public.qoima_movements (organization_id, owner_id, product_id, movement_type, quantity, balance_after,
                                                    warehouse_id, document_id, price, note, created_at)
                values (v_org, v_uid, v_p.id, 'ADJUST', v_counted - v_p.main_q, v_total, w_main, v_doc, v_p.buy * 100,
                        'Плановая инвентаризация', v_base + interval '2 hours');
            end loop;
        end if;

        -- issues: no work on Sundays
        continue when v_day = 60 or extract(isodow from v_base at time zone 'Asia/Almaty') = 7;
        for v_wh in 1..2 loop
            v_doc := null;
            for v_p in select d.*, coalesce((select quantity from public.qoima_stock s
                                             where s.product_id = d.id and s.warehouse_id = case v_wh when 1 then w_main else w_shop end), 0) as cur_q
                       from demo_items d order by d.sku loop
                -- the main warehouse issues ~the daily rate, the shop sells a smaller share
                v_qty := floor(v_p.rate * (case v_wh when 1 then 1.0 else 0.25 end) * (0.4 + random() * 1.2) + random())::integer;
                v_cur := v_p.cur_q;
                v_qty := least(v_qty, v_cur);
                continue when v_qty <= 0;
                if v_doc is null then
                    n_out := n_out + 1;
                    insert into public.qoima_documents (organization_id, number, doc_type, warehouse_id, counterparty, note, created_by, created_at)
                    values (v_org, n_out, 'OUT', case v_wh when 1 then w_main else w_shop end,
                            case v_wh when 1 then v_clients[1 + floor(random() * array_length(v_clients, 1))::integer] else 'Розничные продажи' end,
                            '', v_uid, v_base + interval '4 hours' + v_wh * interval '50 minutes' + floor(random() * 30) * interval '1 minute')
                    returning id into v_doc;
                end if;
                v_total := public.qoima_apply_stock(v_org, v_p.id, case v_wh when 1 then w_main else w_shop end, -v_qty);
                insert into public.qoima_movements (organization_id, owner_id, product_id, movement_type, quantity, balance_after,
                                                    warehouse_id, document_id, price, note, created_at)
                select v_org, v_uid, v_p.id, 'OUT', v_qty, v_total, d.warehouse_id, v_doc, v_p.sell * 100, '', d.created_at
                from public.qoima_documents d where d.id = v_doc;
            end loop;
        end loop;
    end loop;

    update public.qoima_products set updated_at = v_now where organization_id = v_org;
    raise notice 'Demo account ready: % / % (documents: IN %, OUT %, TRANSFER %, ADJUST %)',
        c_email, c_password, n_in, n_out, n_tr, n_adj;
end;
$$;
