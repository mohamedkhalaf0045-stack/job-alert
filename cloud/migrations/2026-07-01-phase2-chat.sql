-- Phase 2: HR-to-candidate chat system
-- Run this once in Supabase SQL Editor. Idempotent: safe to re-run.
--
-- Creates tables for conversations, messages, message reports, and blocked users.
-- Implements RLS policies to ensure users can only see/manage their own conversations.

-- ── conversations table ──────────────────────────────────────────────────────
-- Represents a chat thread between HR and a candidate.
-- job_posting_id is nullable (HR can message without a specific job posting context).

create table if not exists public.conversations (
    id               uuid primary key default gen_random_uuid(),
    job_posting_id   uuid references public.job_postings(id) on delete set null,
    candidate_id     uuid not null references public.profiles(id) on delete cascade,
    employer_id      uuid not null references public.profiles(id) on delete cascade,
    initiated_by     text not null check (initiated_by in ('candidate', 'employer')),
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    -- Unique constraint: only one conversation per (job_posting, candidate, employer) pair
    unique (job_posting_id, candidate_id, employer_id)
);

create index if not exists conversations_candidate_idx on public.conversations(candidate_id);
create index if not exists conversations_employer_idx on public.conversations(employer_id);
create index if not exists conversations_job_posting_idx on public.conversations(job_posting_id);

alter table public.conversations enable row level security;

-- ── messages table ──────────────────────────────────────────────────────────
-- Stores individual messages within a conversation.

create table if not exists public.messages (
    id               uuid primary key default gen_random_uuid(),
    conversation_id  uuid not null references public.conversations(id) on delete cascade,
    sender_id        uuid not null references public.profiles(id) on delete set null,
    content          text not null,
    sent_at          timestamptz not null default now(),
    read_at          timestamptz,
    created_at       timestamptz not null default now()
);

create index if not exists messages_conversation_idx on public.messages(conversation_id);
create index if not exists messages_sender_idx on public.messages(sender_id);
create index if not exists messages_sent_at_idx on public.messages(sent_at);

alter table public.messages enable row level security;

-- ── blocked_users column in profiles ─────────────────────────────────────────
-- JSONB array of user IDs that this profile has blocked.
-- Implementation: check if blocked_users array contains a user_id before allowing
-- conversation creation or message delivery.

alter table public.profiles add column if not exists blocked_users uuid[] default array[]::uuid[];

-- ── message_reports table ───────────────────────────────────────────────────
-- Moderation table: reports messages for spam, abuse, or policy violations.

create table if not exists public.message_reports (
    id               uuid primary key default gen_random_uuid(),
    message_id       uuid not null references public.messages(id) on delete cascade,
    reporter_id      uuid not null references public.profiles(id) on delete set null,
    reason           text not null,
    reported_at      timestamptz not null default now(),
    resolved         boolean not null default false,
    admin_notes      text,
    created_at       timestamptz not null default now()
);

create index if not exists message_reports_message_idx on public.message_reports(message_id);
create index if not exists message_reports_reporter_idx on public.message_reports(reporter_id);
create index if not exists message_reports_resolved_idx on public.message_reports(resolved);

alter table public.message_reports enable row level security;

-- ── RLS Policies: conversations ──────────────────────────────────────────────

-- Candidate/Employer can see conversations they are a participant in
drop policy if exists conversations_select_own on public.conversations;
create policy conversations_select_own on public.conversations
    for select to authenticated
    using (
        auth.uid() = candidate_id or auth.uid() = employer_id
    );

-- Candidate can initiate a conversation (insert) if they are the candidate
drop policy if exists conversations_insert_candidate on public.conversations;
create policy conversations_insert_candidate on public.conversations
    for insert to authenticated
    with check (
        auth.uid() = candidate_id and initiated_by = 'candidate'
    );

-- Employer can initiate a conversation (insert) if they are the employer
drop policy if exists conversations_insert_employer on public.conversations;
create policy conversations_insert_employer on public.conversations
    for insert to authenticated
    with check (
        auth.uid() = employer_id and initiated_by = 'employer'
    );

-- Only conversation participants can update the conversation (e.g., update updated_at)
drop policy if exists conversations_update_own on public.conversations;
create policy conversations_update_own on public.conversations
    for update to authenticated
    using (
        auth.uid() = candidate_id or auth.uid() = employer_id
    )
    with check (
        auth.uid() = candidate_id or auth.uid() = employer_id
    );

-- ── RLS Policies: messages ──────────────────────────────────────────────────

-- Only conversation participants can see messages in that conversation
drop policy if exists messages_select_own_conversation on public.messages;
create policy messages_select_own_conversation on public.messages
    for select to authenticated
    using (
        conversation_id in (
            select id from public.conversations
            where candidate_id = auth.uid() or employer_id = auth.uid()
        )
    );

-- Only conversation participants can insert messages (must be a participant in the conversation)
drop policy if exists messages_insert_own_conversation on public.messages;
create policy messages_insert_own_conversation on public.messages
    for insert to authenticated
    with check (
        conversation_id in (
            select id from public.conversations
            where (candidate_id = auth.uid() or employer_id = auth.uid())
        )
        and sender_id = auth.uid()
    );

-- Users can update their own message (mark read)
drop policy if exists messages_update_own on public.messages;
create policy messages_update_own on public.messages
    for update to authenticated
    using (
        conversation_id in (
            select id from public.conversations
            where candidate_id = auth.uid() or employer_id = auth.uid()
        )
    )
    with check (
        conversation_id in (
            select id from public.conversations
            where candidate_id = auth.uid() or employer_id = auth.uid()
        )
    );

-- ── RLS Policies: message_reports ───────────────────────────────────────────

-- Authenticated users can report messages
drop policy if exists message_reports_insert_any on public.message_reports;
create policy message_reports_insert_any on public.message_reports
    for insert to authenticated
    with check (
        reporter_id = auth.uid()
    );

-- Users can see their own reports
drop policy if exists message_reports_select_own on public.message_reports;
create policy message_reports_select_own on public.message_reports
    for select to authenticated
    using (
        reporter_id = auth.uid()
    );

-- Admin (service_role) can see all reports and update resolved status
-- This is handled at the application level via admin API routes
