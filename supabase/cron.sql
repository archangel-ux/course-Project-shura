-- Daily low-stock digest at 09:00 Almaty (04:00 UTC), scheduled inside Supabase.
-- Replace the two placeholders below and run this file in the SQL Editor.
-- The site must be reachable from the internet (a deployed URL, not localhost).
--    <SITE_URL>    — the public address of the site, e.g. https://qoima.onrender.com
--    <CRON_SECRET> — the same value as the CRON_SECRET environment variable:
--                    select value from qoima_private.settings where key = 'cron_secret';

-- the scheduler and the HTTP client (same as Dashboard → Database → Extensions → pg_cron, pg_net)
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

select cron.unschedule('qoima-low-stock') where exists (select 1 from cron.job where jobname = 'qoima-low-stock');

select cron.schedule(
    'qoima-low-stock',
    '0 4 * * *',
    $$ select net.http_get(
           url := '<SITE_URL>/cron/low-stock',
           headers := jsonb_build_object('X-Cron-Secret', '<CRON_SECRET>'),
           timeout_milliseconds := 60000
       ) $$
);
