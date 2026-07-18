-- BiasRadar security boundary: constraints, RLS, and atomic analysis persistence.
-- Review on a staging project first. Existing invalid or duplicate data will cause
-- this migration to fail instead of silently discarding data.

alter table public.topics enable row level security;
alter table public.sources enable row level security;
alter table public.raw_items enable row level security;
alter table public.analysis enable row level security;
alter table public.claims enable row level security;
alter table public.claim_checks enable row level security;
alter table public.topic_reports enable row level security;

-- BiasRadar currently has no direct browser/database client. Keep the exposed Data
-- API closed to low-privilege roles until explicit product policies are designed.
revoke all on table public.topics from anon, authenticated;
revoke all on table public.sources from anon, authenticated;
revoke all on table public.raw_items from anon, authenticated;
revoke all on table public.analysis from anon, authenticated;
revoke all on table public.claims from anon, authenticated;
revoke all on table public.claim_checks from anon, authenticated;
revoke all on table public.topic_reports from anon, authenticated;

alter table public.raw_items
  add constraint raw_items_url_unique unique (url);

alter table public.analysis
  add constraint analysis_raw_item_unique unique (raw_item_id),
  add constraint analysis_stance_valid check (
    stance in (
      'anti_subject', 'pro_subject', 'neutral', 'mixed', 'unclear',
      'institutional_defense', 'conspiracy_claim',
      'evidence_based_criticism', 'fan_emotion'
    )
  ),
  add constraint analysis_stance_confidence_range
    check (stance_confidence between 0 and 1),
  add constraint analysis_bias_score_range check (bias_score between 0 and 1),
  add constraint analysis_loaded_language_score_range
    check (loaded_language_score between 0 and 1),
  add constraint analysis_one_sidedness_score_range
    check (one_sidedness_score between 0 and 1),
  add constraint analysis_evidence_quality_score_range
    check (evidence_quality_score between 0 and 1),
  add constraint analysis_emotionality_score_range
    check (emotionality_score between 0 and 1);

alter table public.claims
  add constraint claims_type_valid check (
    claim_type in (
      'verifiable_fact', 'interpretation', 'opinion', 'allegation',
      'prediction', 'quote'
    )
  ),
  add constraint claims_checkability_valid check (
    checkability in ('checkable', 'partly_checkable', 'not_checkable')
  ),
  add constraint claims_importance_score_range
    check (importance_score between 0 and 1);

create index if not exists raw_items_topic_id_idx on public.raw_items (topic_id);
create index if not exists claims_raw_item_id_idx on public.claims (raw_item_id);

create or replace function public.save_article_analysis(
  p_raw_item_id uuid,
  p_analysis jsonb,
  p_claims jsonb,
  p_cleaned_text text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_analysis_id uuid;
begin
  if not exists (
    select 1 from public.raw_items where id = p_raw_item_id for update
  ) then
    raise exception 'raw item does not exist' using errcode = '23503';
  end if;

  insert into public.analysis (
    raw_item_id, stance, stance_confidence, bias_direction, bias_score,
    loaded_language_score, one_sidedness_score, evidence_quality_score,
    emotionality_score, missing_counterarguments, loaded_terms, summary, reasoning
  ) values (
    p_raw_item_id,
    p_analysis->>'stance',
    (p_analysis->>'stance_confidence')::numeric,
    p_analysis->>'bias_direction',
    (p_analysis->>'bias_score')::numeric,
    (p_analysis->>'loaded_language_score')::numeric,
    (p_analysis->>'one_sidedness_score')::numeric,
    (p_analysis->>'evidence_quality_score')::numeric,
    (p_analysis->>'emotionality_score')::numeric,
    array(select jsonb_array_elements_text(p_analysis->'missing_counterarguments')),
    array(select jsonb_array_elements_text(p_analysis->'loaded_terms')),
    p_analysis->>'summary',
    p_analysis->>'reasoning'
  )
  returning id into v_analysis_id;

  insert into public.claims (
    raw_item_id, claim_text, claim_type, checkability, importance_score
  )
  select
    p_raw_item_id,
    item.claim_text,
    item.claim_type,
    item.checkability,
    item.importance_score
  from jsonb_to_recordset(coalesce(p_claims, '[]'::jsonb)) as item(
    claim_text text,
    claim_type text,
    checkability text,
    importance_score numeric
  );

  update public.raw_items
  set cleaned_text = p_cleaned_text, status = 'analyzed'
  where id = p_raw_item_id;

  return v_analysis_id;
end;
$$;

revoke execute on function public.save_article_analysis(uuid, jsonb, jsonb, text)
  from public, anon, authenticated;
grant execute on function public.save_article_analysis(uuid, jsonb, jsonb, text)
  to service_role;
