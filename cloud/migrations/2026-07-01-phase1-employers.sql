-- Phase 1: Two-Sided Job Marketplace — Employer Profiles + Job Postings
-- Run once in Supabase SQL Editor (after auth-profiles and job tables exist).
-- Idempotent: safe to re-run.
--
-- Creates the foundation for employers to post jobs directly (not just scraped).
-- Candidates see union of scraped + employer-posted jobs in the feed.

-- 1. Employers table —————————————————————————————————————————————————
create table if not exists public.employers (
    id              uuid primary key default gen_random_uuid(),
    owner_user_id   uuid not null references auth.users(id) on delete cascade,
    name            text not null,
    logo_url        text,
    industry        text,
    size            text,
    location        text,
    description     text,
    verified        boolean not null default false,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique(owner_user_id)  -- one employer profile per user
);

create index if not exists employers_owner_user_id_idx on public.employers(owner_user_id);

alter table public.employers enable row level security;

-- Owner can read/update/delete own employer profile
drop policy if exists employers_owner_full on public.employers;
create policy employers_owner_full on public.employers
    for all to authenticated
    using (owner_user_id = auth.uid())
    with check (owner_user_id = auth.uid());

-- Unauthenticated users can view employer profiles (public listing)
drop policy if exists employers_public_read on public.employers;
create policy employers_public_read on public.employers
    for select using (true);


-- 2. Job Postings table —————————————————————————————————————————————————
create table if not exists public.job_postings (
    id              uuid primary key default gen_random_uuid(),
    employer_id     uuid not null references public.employers(id) on delete cascade,
    title           text not null,
    description     text,
    requirements    text,
    location        text,
    salary_min      numeric,
    salary_max      numeric,
    employment_type text,
    status          text not null default 'draft'
                    check (status in ('draft', 'published', 'closed')),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    expires_at      timestamptz
);

create index if not exists job_postings_employer_id_idx on public.job_postings(employer_id);
create index if not exists job_postings_status_idx on public.job_postings(status);
create index if not exists job_postings_created_at_idx on public.job_postings(created_at desc);

alter table public.job_postings enable row level security;

-- Only the employer (via their owner_user_id) can CRUD their own postings
drop policy if exists job_postings_employer_own on public.job_postings;
create policy job_postings_employer_own on public.job_postings
    for all to authenticated
    using (employer_id in (select id from public.employers where owner_user_id = auth.uid()))
    with check (employer_id in (select id from public.employers where owner_user_id = auth.uid()));

-- Public read: anyone can see published job postings
drop policy if exists job_postings_public_read on public.job_postings;
create policy job_postings_public_read on public.job_postings
    for select using (status = 'published');


-- 3. Alter profiles: add user_type + employer_id ——————————————————————
alter table public.profiles add column if not exists user_type text default 'candidate'
    check (user_type in ('candidate', 'employer'));

alter table public.profiles add column if not exists employer_id uuid references public.employers(id) on delete set null;

create index if not exists profiles_user_type_idx on public.profiles(user_type);
create index if not exists profiles_employer_id_idx on public.profiles(employer_id);


-- 4. Alter jobs: add source_type ———————————————————————————————————————
-- Tracks whether a job was scraped or posted by an employer
alter table public.jobs add column if not exists source_type text default 'scraped'
    check (source_type in ('scraped', 'employer_posted'));

-- job_posting_id points to the job_postings table for employer-posted jobs
alter table public.jobs add column if not exists job_posting_id uuid references public.job_postings(id) on delete cascade;

create index if not exists jobs_source_type_idx on public.jobs(source_type);
create index if not exists jobs_job_posting_id_idx on public.jobs(job_posting_id);


-- 5. Auto-link user profile to employer on signup ————————————————————
-- When a new user signs up (trigger via handle_new_user), if they
-- later claim they are an employer, we create the link.
-- For now, this is manual via the API. The trigger remains as-is.

-- If you want to auto-create an employer profile on signup for users who
-- select "employer" as their user_type, modify handle_new_user() here:
-- (We skip this in Phase 1; employers explicitly create profiles via API.)

-- 6. Verification helper: enforce jobs.job_posting_id only for employer_posted
alter table public.jobs add constraint jobs_posting_id_check check (
    (source_type = 'employer_posted' and job_posting_id is not null) or
    (source_type = 'scraped' and job_posting_id is null)
);


-- 7. Trigger: auto-create jobs entry when posting is published —————————
-- When a job_posting transitions to 'published', create an entry in the
-- jobs table (source_type='employer_posted') so it appears in the feed.
create or replace function public.sync_job_posting_to_jobs()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    v_job_id text;
    v_company_name text;
begin
    -- Only create jobs entry if transitioning to 'published'
    if new.status = 'published' and (old is null or old.status <> 'published') then
        -- Fetch employer name for the jobs.company column
        select name into v_company_name from public.employers
         where id = new.employer_id;

        -- Generate a unique job_id (format: "employer_job_{id}_{uuid_short}")
        v_job_id := 'employer_job_' || substring(new.id::text, 1, 8) || '_' || substring(gen_random_uuid()::text, 1, 8);

        insert into public.jobs (
            job_id, title, company, location, source, url, source_type,
            job_posting_id, date_posted, date_collected, status
        ) values (
            v_job_id,
            new.title,
            coalesce(v_company_name, 'Company'),
            new.location,
            coalesce(v_company_name, 'Direct Posting'),
            '',  -- no external URL for direct postings
            'employer_posted',
            new.id,
            new.created_at,
            new.created_at,
            'active'
        )
        on conflict (job_id) do nothing;
    end if;

    -- If transitioning away from published (e.g., to closed), mark the jobs entry as closed
    if old.status = 'published' and new.status <> 'published' then
        update public.jobs
           set status = 'closed'
         where job_posting_id = new.id
           and source_type = 'employer_posted';
    end if;

    return new;
end;
$$;

drop trigger if exists trg_sync_job_posting_to_jobs on public.job_postings;
create trigger trg_sync_job_posting_to_jobs
    after insert or update on public.job_postings
    for each row execute function public.sync_job_posting_to_jobs();
