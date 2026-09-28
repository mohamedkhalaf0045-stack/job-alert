-- user_jobs_feed previously treated an UNSCORED job (llm_score IS NULL) as an
-- automatic pass of the min_score filter:
--   and (v_min is null or j.llm_score is null or j.llm_score >= v_min)
-- With a large unscored backlog (Groq outages), this surfaced jobs that were
-- never AI-vetted at all as "matches" purely on a keyword text match — e.g.
-- "Sales Account Manager", "UAV Ground Control Station Engineer" showing up
-- for an IT-support profile. Require the job to actually be scored (and meet
-- the threshold) before it counts as a match; unscored jobs simply wait for
-- the next enricher pass instead of leaking through unfiltered.
CREATE OR REPLACE FUNCTION public.user_jobs_feed(p_user uuid DEFAULT NULL::uuid, p_limit integer DEFAULT 30, p_before timestamp with time zone DEFAULT NULL::timestamp with time zone)
 RETURNS TABLE(job_id text, title text, company text, location text, url text, source text, date_posted timestamp with time zone, date_collected timestamp with time zone, llm_score integer, llm_summary text, matched_skills jsonb, salary_min numeric, salary_max numeric, salary_avg numeric, salary_currency text, salary_period text, salary_source text, my_status text, source_type text)
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'public'
AS $function$
declare
  v_user         uuid;
  v_kw           text[];
  v_loc          text[];
  v_excl         text[];
  v_min          smallint;
  v_tsq          tsquery := null;
  v_excl_tsq     tsquery := null;
  v_loc_patterns text[]  := null;
  kw_item        text;
  q_item         tsquery;
begin
  v_user := coalesce(p_user, auth.uid());
  if auth.uid() is not null and v_user <> auth.uid() then
    v_user := auth.uid();
  end if;
  if v_user is null then return; end if;

  select up.keywords, up.locations, up.exclude_keywords, up.min_score
    into v_kw, v_loc, v_excl, v_min
    from public.user_preferences up
   where up.user_id = v_user;

  if v_kw is not null and cardinality(v_kw) > 0 then
    foreach kw_item in array v_kw loop
      q_item := phraseto_tsquery('english', kw_item)
             || phraseto_tsquery('simple',  kw_item);
      v_tsq  := case when v_tsq is null then q_item else v_tsq || q_item end;
    end loop;
  end if;

  if v_excl is not null and cardinality(v_excl) > 0 then
    foreach kw_item in array v_excl loop
      q_item     := phraseto_tsquery('english', kw_item)
                 || phraseto_tsquery('simple',  kw_item);
      v_excl_tsq := case when v_excl_tsq is null then q_item else v_excl_tsq || q_item end;
    end loop;
  end if;

  if v_loc is not null and cardinality(v_loc) > 0 then
    select array_agg('%' || replace(replace(l, '%', ''), '_', '') || '%')
      into v_loc_patterns
      from unnest(v_loc) as l
     where length(trim(l)) > 0;
  end if;

  return query
    select combined.job_id, combined.title, combined.company, combined.location,
           combined.url, combined.source, combined.date_posted, combined.date_collected,
           combined.llm_score, combined.llm_summary, combined.matched_skills,
           combined.salary_min, combined.salary_max, combined.salary_avg,
           combined.salary_currency, combined.salary_period, combined.salary_source,
           combined.my_status, combined.source_type
      from (
        select j.job_id, j.title, j.company, j.location, j.url, j.source,
               j.date_posted, j.date_collected, j.llm_score, j.llm_summary,
               j.matched_skills, j.salary_min, j.salary_max, j.salary_avg,
               j.salary_currency, j.salary_period, j.salary_source,
               i.status as my_status, j.source_type
          from public.jobs j
          left join public.user_job_interactions i
                 on i.job_id = j.job_id and i.user_id = v_user
         where j.source_type = 'scraped'
           and j.duplicate_of_url is null
           and (v_tsq is null or j.search_tsv @@ v_tsq)
           and (v_excl_tsq is null or not (j.search_tsv @@ v_excl_tsq))
           and (v_loc_patterns is null or j.location ilike any (v_loc_patterns))
           and j.llm_score is not null
           and (v_min is null or j.llm_score >= v_min)
           and coalesce(i.status, '') not in ('dismissed', 'hidden')

        union all

        select j.job_id, jp.title, e.name, jp.location, j.url, e.name,
               jp.created_at, jp.created_at, j.llm_score, j.llm_summary,
               j.matched_skills, jp.salary_min, jp.salary_max, null,
               null, null, null,
               i.status as my_status, j.source_type
          from public.jobs j
          inner join public.job_postings jp on j.job_posting_id = jp.id
          inner join public.employers e on jp.employer_id = e.id
          left join public.user_job_interactions i
                 on i.job_id = j.job_id and i.user_id = v_user
         where j.source_type = 'employer_posted'
           and jp.status = 'published'
           and (jp.expires_at is null or jp.expires_at > now())
           and (
             v_tsq is null or (
               to_tsvector('english', coalesce(jp.title,'') || ' ' || coalesce(jp.description,'') || ' ' || coalesce(e.name,''))
               || to_tsvector('simple', coalesce(jp.title,'') || ' ' || coalesce(jp.description,'') || ' ' || coalesce(e.name,''))
             ) @@ v_tsq
           )
           and (
             v_excl_tsq is null or not ((
               to_tsvector('english', coalesce(jp.title,'') || ' ' || coalesce(jp.description,'') || ' ' || coalesce(e.name,''))
               || to_tsvector('simple', coalesce(jp.title,'') || ' ' || coalesce(jp.description,'') || ' ' || coalesce(e.name,''))
             ) @@ v_excl_tsq)
           )
           and (v_loc_patterns is null or jp.location ilike any (v_loc_patterns))
           and coalesce(i.status, '') not in ('dismissed', 'hidden')
      ) combined
      order by
        -- employer posts always first
        case when combined.source_type = 'employer_posted' then 0 else 1 end,
        -- scraped: newest day first, then best score within that day
        combined.date_collected::date desc nulls last,
        combined.llm_score desc nulls last,
        combined.date_collected desc nulls last
      limit greatest(1, least(p_limit, 100));
end;
$function$
