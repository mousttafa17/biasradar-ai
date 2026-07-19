-- Topic-agnostic primary evidence candidates, immutable automation, and human review.
-- Apply after 202607190009_topic_intake_queue.sql.

create table public.evidence_candidates (
  id uuid primary key default gen_random_uuid(),
  claim_id uuid not null references public.claims(id) on delete cascade,
  url text not null,
  canonical_url text not null,
  title text not null,
  publisher text not null,
  published_at timestamp with time zone,
  source_domain text not null,
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  discovery_method text not null,
  retrieved_at timestamp with time zone not null default now(),
  review_status text not null default 'pending' check (
    review_status in ('pending', 'approved', 'rejected', 'needs_more_evidence')
  ),
  unique (claim_id, canonical_url)
);

create table public.evidence_automated_assessments (
  id uuid primary key default gen_random_uuid(),
  evidence_candidate_id uuid not null references public.evidence_candidates(id)
    on delete cascade,
  relation text not null check (relation in (
    'supports', 'contradicts', 'partially_supports', 'provides_context',
    'irrelevant', 'insufficient'
  )),
  source_role text not null check (source_role in (
    'primary_record', 'official_statement', 'direct_transcript',
    'independent_secondary', 'repetition', 'unknown'
  )),
  relevance_score numeric not null check (relevance_score between 0 and 1),
  excerpt text not null check (length(excerpt) <= 2000),
  reasoning text not null check (length(reasoning) between 1 and 2000),
  method_version text not null,
  model_id text not null,
  created_at timestamp with time zone not null default now(),
  unique (evidence_candidate_id, method_version, model_id)
);

create table public.evidence_reviews (
  id uuid primary key default gen_random_uuid(),
  evidence_candidate_id uuid not null references public.evidence_candidates(id)
    on delete cascade,
  reviewer_user_id uuid not null references auth.users(id),
  decision text not null check (
    decision in ('approved', 'rejected', 'needs_more_evidence')
  ),
  corrected_relation text check (corrected_relation is null or corrected_relation in (
    'supports', 'contradicts', 'partially_supports', 'provides_context',
    'irrelevant', 'insufficient'
  )),
  corrected_source_role text check (
    corrected_source_role is null or corrected_source_role in (
      'primary_record', 'official_statement', 'direct_transcript',
      'independent_secondary', 'repetition', 'unknown'
    )
  ),
  corrected_excerpt text check (
    corrected_excerpt is null or length(corrected_excerpt) <= 2000
  ),
  final_verdict text check (final_verdict is null or final_verdict in (
    'supported', 'contradicted', 'unverified', 'misleading', 'opinion',
    'needs_human_review'
  )),
  confidence numeric check (confidence is null or confidence between 0 and 1),
  notes text not null default '' check (length(notes) <= 4000),
  created_at timestamp with time zone not null default now()
);

create index evidence_candidates_claim_status_idx
  on public.evidence_candidates (claim_id, review_status);
create index evidence_candidates_review_queue_idx
  on public.evidence_candidates (review_status, retrieved_at);
create index evidence_reviews_candidate_created_idx
  on public.evidence_reviews (evidence_candidate_id, created_at desc);

alter table public.evidence_candidates enable row level security;
alter table public.evidence_automated_assessments enable row level security;
alter table public.evidence_reviews enable row level security;
revoke all on table public.evidence_candidates from anon, authenticated;
revoke all on table public.evidence_automated_assessments from anon, authenticated;
revoke all on table public.evidence_reviews from anon, authenticated;

create or replace function public.submit_evidence_review(
  p_candidate_id uuid,
  p_reviewer_user_id uuid,
  p_decision text,
  p_corrected_relation text,
  p_corrected_source_role text,
  p_corrected_excerpt text,
  p_final_verdict text,
  p_confidence numeric,
  p_notes text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_review_id uuid;
begin
  if not exists (
    select 1 from auth.users
    where id = p_reviewer_user_id
      and raw_app_meta_data->>'role' = 'evidence_reviewer'
  ) then
    raise exception 'reviewer role required' using errcode = '42501';
  end if;
  insert into public.evidence_reviews (
    evidence_candidate_id, reviewer_user_id, decision, corrected_relation,
    corrected_source_role, corrected_excerpt, final_verdict, confidence, notes
  ) values (
    p_candidate_id, p_reviewer_user_id, p_decision, p_corrected_relation,
    p_corrected_source_role, p_corrected_excerpt, p_final_verdict, p_confidence,
    p_notes
  ) returning id into v_review_id;
  update public.evidence_candidates set review_status = p_decision
  where id = p_candidate_id;
  if not found then
    raise exception 'evidence candidate does not exist' using errcode = '23503';
  end if;
  return v_review_id;
end;
$$;

revoke execute on function public.submit_evidence_review(
  uuid, uuid, text, text, text, text, text, numeric, text
) from public, anon, authenticated;
grant execute on function public.submit_evidence_review(
  uuid, uuid, text, text, text, text, text, numeric, text
) to service_role;
