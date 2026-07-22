-- Baseline BiasRadar tables required before the hardening and feature migrations.
-- Supabase supplies auth.users, anon/authenticated/service_role, and gen_random_uuid().

create table if not exists public.topics (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  subject text,
  supporting_frame text,
  opposing_frame text,
  keywords text[] not null default '{}',
  status text not null default 'active',
  created_at timestamp with time zone not null default now()
);

create table if not exists public.sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  domain text,
  source_type text,
  reliability_score numeric not null default 0.5,
  created_at timestamp with time zone not null default now()
);

create table if not exists public.raw_items (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid references public.topics(id),
  source_name text not null,
  source_type text not null default 'news',
  title text not null,
  url text not null,
  author text,
  published_at timestamp with time zone,
  fetched_at timestamp with time zone not null default now(),
  raw_text text,
  cleaned_text text,
  status text not null default 'new',
  created_at timestamp with time zone not null default now()
);

create table if not exists public.analysis (
  id uuid primary key default gen_random_uuid(),
  raw_item_id uuid not null references public.raw_items(id) on delete cascade,
  stance text not null,
  stance_confidence numeric not null,
  bias_direction text not null,
  bias_score numeric not null,
  loaded_language_score numeric not null,
  one_sidedness_score numeric not null,
  evidence_quality_score numeric not null,
  emotionality_score numeric not null,
  missing_counterarguments text[] not null default '{}',
  loaded_terms text[] not null default '{}',
  summary text not null,
  reasoning text not null,
  created_at timestamp with time zone not null default now()
);

create table if not exists public.claims (
  id uuid primary key default gen_random_uuid(),
  raw_item_id uuid not null references public.raw_items(id) on delete cascade,
  claim_text text not null,
  claim_type text not null,
  checkability text not null,
  importance_score numeric not null,
  created_at timestamp with time zone not null default now()
);

create table if not exists public.claim_checks (
  id uuid primary key default gen_random_uuid(),
  claim_id uuid not null references public.claims(id) on delete cascade,
  verdict text not null,
  confidence numeric not null,
  evidence_summary text not null,
  evidence_urls text[] not null default '{}',
  notes text not null default '',
  checked_at timestamp with time zone not null default now()
);

create table if not exists public.topic_reports (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid not null references public.topics(id) on delete cascade,
  period_start timestamp with time zone not null,
  period_end timestamp with time zone not null,
  total_items integer not null default 0,
  pro_percent numeric not null default 0,
  anti_percent numeric not null default 0,
  neutral_percent numeric not null default 0,
  mixed_percent numeric not null default 0,
  overall_bias_score numeric not null default 0,
  report_text text not null,
  created_at timestamp with time zone not null default now()
);
