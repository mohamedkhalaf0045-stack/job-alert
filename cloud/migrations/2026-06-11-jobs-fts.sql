-- Multi-user website — Phase 1e: jobs full-text search + per-user feed function
-- Run once in Supabase SQL Editor (after the per-user tables exist).
-- Idempotent and SAFE: adds a column/indexes/function only; changes no policies,
-- so it cannot break the existing scraper. (The RLS write-lockdown is a
-- separate, gated migration: 2026-06-11-jobs-rls-lockdown.sql.)

-- 1. Full-text search over title + company + location -------------------------
-- 'simple' config (not 'english') avoids over-stemming technical/brand terms,
-- and is IMMUTABLE so it is valid in a generated column.
alter table public.jobs add column if not exists search_tsv tsvector
    generated always as (
        to_tsvector('simple',
            coalesce(title, '') || ' ' || coalesce(company, '') || ' ' || coalesce(location, ''))
    ) stored;

create index if not exists jobs_search_tsv_idx     on public.jobs using gin (search_tsv);
create index if not exists jobs_date_collected_idx on public.jobs (date_collected desc);

-- 2. Per-user feed over the shared global pool --------------------------------
-- Returns the curated columns the feed UI needs plus the caller's own
-- interaction status. Authenticated callers can only get their OWN feed
-- (p_user is coerced to auth.uid()); the service_role alert sender passes an
-- explicit p_user. Keyset pagination via p_before (date_collected cursor).
create or replace function public.user_jobs_feed(
    p_user   uuid        default null,
    p_limit  int         default 30,
    p_before timestamptz default null
)
returns table (
    job_id          text,
    title           text,
    company         text,
    location        text,
    url             text,
    source          text,
    date_posted     timestamptz,
    date_collected  timestamptz,
    llm_score       smallint,
    llm_summary     text,
    matched_skills  jsonb,
    salary_min      numeric,
    salary_max      numeric,
    salary_avg      numeric,
    salary_currency text,
    salary_period   text,
    salary_source   text,
    my_status       text
)
language plpgsql
stable
security invoker
as $$
declare
    v_user         uuid;
    v_kw           text[];
    v_loc          text[];
    v_excl         text[];
    v_min          smallint;
    v_tsq          tsquery := null;
    v_excl_tsq     tsquery := null;
    v_loc_patterns text[]  := null;
begin
    v_user := coalesce(p_user, auth.uid());
    -- An authenticated client may only ever read its own feed.
    if auth.uid() is not null and v_user <> auth.uid() then
        v_user := auth.uid();
    end if;
    if v_user is null then
        return;  -- no user context
    end if;

    select up.keywords, up.locations, up.exclude_keywords, up.min_score
      into v_kw, v_loc, v_excl, v_min
      from public.user_preferences up
     where up.user_id = v_user;

    -- websearch_to_tsquery is injection-safe (treats input as a search string);
    -- joining terms with " or " gives OR-across-terms, AND-within-a-term.
    if v_kw is not null and cardinality(v_kw) > 0 then
        v_tsq := websearch_to_tsquery('simple', array_to_string(v_kw, ' or '));
    end if;
    if v_excl is not null and cardinality(v_excl) > 0 then
        v_excl_tsq := websearch_to_tsquery('simple', array_to_string(v_excl, ' or '));
    end if;
    if v_loc is not null and cardinality(v_loc) > 0 then
        select array_agg('%' || replace(replace(l, '%', ''), '_', '') || '%')
          into v_loc_patterns
          from unnest(v_loc) as l
         where length(trim(l)) > 0;
    end if;

    return query
        select j.job_id, j.title, j.company, j.location, j.url, j.source,
               j.date_posted, j.date_collected, j.llm_score, j.llm_summary,
               j.matched_skills, j.salary_min, j.salary_max, j.salary_avg,
               j.salary_currency, j.salary_period, j.salary_source,
               i.status as my_status
          from public.jobs j
          left join public.user_job_interactions i
                 on i.job_id = j.job_id and i.user_id = v_user
         where j.duplicate_of_url is null
           and (v_tsq is null or j.search_tsv @@ v_tsq)
           and (v_excl_tsq is null or not (j.search_tsv @@ v_excl_tsq))
           and (v_loc_patterns is null or j.location ilike any (v_loc_patterns))
           and (v_min is null or j.llm_score is null or j.llm_score >= v_min)
           and coalesce(i.status, '') not in ('dismissed', 'hidden')
           and (p_before is null or j.date_collected < p_before)
         order by j.date_collected desc
         limit greatest(1, least(p_limit, 100));
end;
$$;
