-- Topic-agnostic intake and viability gateway.
-- Apply after 202607180007_pipeline_runs.sql.

create table public.topic_submissions (
  id uuid primary key default gen_random_uuid(),
  raw_query text not null check (length(raw_query) between 10 and 500),
  normalized_query text not null check (length(normalized_query) between 10 and 500),
  query_hash text not null unique check (query_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'submitted' check (
    status in (
      'submitted', 'assessing', 'accepted', 'needs_clarification',
      'insufficient_coverage', 'too_broad', 'too_narrow', 'unsafe',
      'duplicate_topic', 'failed'
    )
  ),
  topic_id uuid references public.topics(id),
  created_at timestamp with time zone not null default now(),
  assessed_at timestamp with time zone
);

create table public.topic_viability_assessments (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null unique references public.topic_submissions(id),
  status text not null check (
    status in (
      'accepted', 'needs_clarification', 'insufficient_coverage', 'too_broad',
      'too_narrow', 'unsafe', 'duplicate_topic'
    )
  ),
  confidence numeric not null check (confidence between 0 and 1),
  coverage_signals jsonb not null check (jsonb_typeof(coverage_signals) = 'object'),
  topic_definition jsonb not null check (jsonb_typeof(topic_definition) = 'object'),
  reasons jsonb not null check (jsonb_typeof(reasons) = 'array'),
  clarification_questions jsonb not null default '[]'::jsonb check (
    jsonb_typeof(clarification_questions) = 'array'
  ),
  duplicate_topic_id uuid references public.topics(id),
  prompt_version text not null,
  model_id text not null,
  created_at timestamp with time zone not null default now()
);

create index topic_submissions_status_created_idx
  on public.topic_submissions (status, created_at desc);

alter table public.topic_submissions enable row level security;
alter table public.topic_viability_assessments enable row level security;
revoke all on table public.topic_submissions from anon, authenticated;
revoke all on table public.topic_viability_assessments from anon, authenticated;

create or replace function public.save_topic_viability(
  p_submission_id uuid,
  p_status text,
  p_confidence numeric,
  p_coverage_signals jsonb,
  p_topic_definition jsonb,
  p_reasons jsonb,
  p_clarification_questions jsonb,
  p_duplicate_topic_id uuid,
  p_prompt_version text,
  p_model_id text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_topic_id uuid;
  v_existing_status text;
begin
  if p_status not in (
    'accepted', 'needs_clarification', 'insufficient_coverage', 'too_broad',
    'too_narrow', 'unsafe', 'duplicate_topic'
  ) then
    raise exception 'invalid viability status' using errcode = '22023';
  end if;

  select status, topic_id into v_existing_status, v_topic_id
  from public.topic_submissions
  where id = p_submission_id for update;
  if not found then
    raise exception 'topic submission does not exist' using errcode = '23503';
  end if;
  if v_existing_status in ('accepted', 'duplicate_topic') and v_topic_id is not null then
    return v_topic_id;
  end if;

  if p_status = 'accepted' then
    insert into public.topics (
      name, subject, supporting_frame, opposing_frame, keywords, status
    ) values (
      p_topic_definition->>'canonical_name',
      p_topic_definition->>'subject',
      p_topic_definition->>'supporting_frame',
      p_topic_definition->>'opposing_frame',
      array(select jsonb_array_elements_text(p_topic_definition->'keywords')),
      'active'
    ) returning id into v_topic_id;
  elsif p_status = 'duplicate_topic' then
    v_topic_id := p_duplicate_topic_id;
  end if;

  insert into public.topic_viability_assessments (
    submission_id, status, confidence, coverage_signals, topic_definition,
    reasons, clarification_questions, duplicate_topic_id, prompt_version, model_id
  ) values (
    p_submission_id, p_status, p_confidence, p_coverage_signals,
    p_topic_definition, p_reasons, p_clarification_questions,
    p_duplicate_topic_id, p_prompt_version, p_model_id
  ) on conflict (submission_id) do update set
    status = excluded.status,
    confidence = excluded.confidence,
    coverage_signals = excluded.coverage_signals,
    topic_definition = excluded.topic_definition,
    reasons = excluded.reasons,
    clarification_questions = excluded.clarification_questions,
    duplicate_topic_id = excluded.duplicate_topic_id,
    prompt_version = excluded.prompt_version,
    model_id = excluded.model_id,
    created_at = now();

  update public.topic_submissions
  set status = p_status, topic_id = v_topic_id, assessed_at = now()
  where id = p_submission_id;
  return v_topic_id;
end;
$$;

revoke execute on function public.save_topic_viability(
  uuid, text, numeric, jsonb, jsonb, jsonb, jsonb, uuid, text, text
) from public, anon, authenticated;
grant execute on function public.save_topic_viability(
  uuid, text, numeric, jsonb, jsonb, jsonb, jsonb, uuid, text, text
) to service_role;
