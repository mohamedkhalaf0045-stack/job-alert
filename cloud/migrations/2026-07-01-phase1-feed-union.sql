-- Phase 1: Union scraped + employer-posted jobs in user feed
-- Run after 2026-07-01-phase1-employers.sql
-- Idempotent: replaces the user_jobs_feed() function.
--
-- Returns scraped jobs (source_type='scraped') + published employer jobs
-- (source_type='employer_posted', status='published'), ranked by:
-- - Employer-posted: by posting_date (created_at) DESC
-- - Scraped: by llm_score DESC, then date_collected DESC

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
    my_status       text,
    source_type     text
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

    -- websearch_to_tsquery is injection-safe
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

    -- Union: scraped jobs + employer-posted published jobs
    return query
        select j.job_id, j.title, j.company, j.location, j.url, j.source,
               j.date_posted, j.date_collected, j.llm_score, j.llm_summary,
               j.matched_skills, j.salary_min, j.salary_max, j.salary_avg,
               j.salary_currency, j.salary_period, j.salary_source,
               i.status as my_status,
               j.source_type
          from public.jobs j
          left join public.user_job_interactions i
                 on i.job_id = j.job_id and i.user_id = v_user
         where j.source_type = 'scraped'
           and j.duplicate_of_url is null
           and (v_tsq is null or j.search_tsv @@ v_tsq)
           and (v_excl_tsq is null or not (j.search_tsv @@ v_excl_tsq))
           and (v_loc_patterns is null or j.location ilike any (v_loc_patterns))
           and (v_min is null or j.llm_score is null or j.llm_score >= v_min)
           and coalesce(i.status, '') not in ('dismissed', 'hidden')
        union all
        select j.job_id, jp.title, e.name, jp.location, j.url, e.name,
               jp.created_at, jp.created_at, j.llm_score, j.llm_summary,
               j.matched_skills, jp.salary_min, jp.salary_max, null,
               null, null, null,
               i.status as my_status,
               j.source_type
          from public.jobs j
          inner join public.job_postings jp on j.job_posting_id = jp.id
          inner join public.employers e on jp.employer_id = e.id
          left join public.user_job_interactions i
                 on i.job_id = j.job_id and i.user_id = v_user
         where j.source_type = 'employer_posted'
           and jp.status = 'published'
           and (jp.expires_at is null or jp.expires_at > now())
           and (v_tsq is null or (to_tsvector('simple',
               coalesce(jp.title, '') || ' ' || coalesce(jp.description, '') || ' ' || coalesce(e.name, '')) @@ v_tsq))
           and (v_excl_tsq is null or not (to_tsvector('simple',
               coalesce(jp.title, '') || ' ' || coalesce(jp.description, '') || ' ' || coalesce(e.name, '')) @@ v_excl_tsq))
           and (v_loc_patterns is null or jp.location ilike any (v_loc_patterns))
           and coalesce(i.status, '') not in ('dismissed', 'hidden')
         order by
           -- Employer jobs first by creation date (newest), then scraped by score + date
           case when source_type = 'employer_posted' then 0 else 1 end,
           case when source_type = 'employer_posted' then date_collected desc else null end,
           case when source_type = 'scraped' then llm_score desc nulls last else null end,
           case when source_type = 'scraped' then date_collected desc else null end
         limit greatest(1, least(p_limit, 100));
end;
$$;
