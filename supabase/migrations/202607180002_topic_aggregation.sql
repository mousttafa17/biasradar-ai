-- Separate directional stance from framing characteristics and store frontend-ready
-- deterministic topic reports. Apply after 202607180001_secure_analysis_boundary.sql.

alter table public.analysis
  add column framing_tags text[] not null default '{}';

alter table public.analysis drop constraint analysis_stance_valid;
alter table public.analysis
  add constraint analysis_stance_valid check (
    stance in ('anti_subject', 'pro_subject', 'neutral', 'mixed', 'unclear')
  ),
  add constraint analysis_framing_tags_valid check (
    framing_tags <@ array[
      'institutional_defense', 'conspiracy_claim',
      'evidence_based_criticism', 'fan_emotion'
    ]::text[]
  );

alter table public.topic_reports
  add column unclear_percent numeric,
  add column directional_pro_percent numeric,
  add column directional_anti_percent numeric,
  add column confidence_score numeric,
  add column source_count integer,
  add column report_data jsonb,
  add constraint topic_reports_pro_percent_range check (pro_percent between 0 and 100),
  add constraint topic_reports_anti_percent_range check (anti_percent between 0 and 100),
  add constraint topic_reports_neutral_percent_range check (neutral_percent between 0 and 100),
  add constraint topic_reports_mixed_percent_range check (mixed_percent between 0 and 100),
  add constraint topic_reports_unclear_percent_range check (unclear_percent between 0 and 100),
  add constraint topic_reports_directional_pro_range check (directional_pro_percent between 0 and 100),
  add constraint topic_reports_directional_anti_range check (directional_anti_percent between 0 and 100),
  add constraint topic_reports_bias_score_range check (overall_bias_score between -100 and 100),
  add constraint topic_reports_confidence_range check (confidence_score between 0 and 1),
  add constraint topic_reports_source_count_nonnegative check (source_count >= 0);

create index if not exists topic_reports_topic_period_idx
  on public.topic_reports (topic_id, period_end desc);

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
    raw_item_id, stance, framing_tags, stance_confidence, bias_direction,
    bias_score, loaded_language_score, one_sidedness_score,
    evidence_quality_score, emotionality_score, missing_counterarguments,
    loaded_terms, summary, reasoning
  ) values (
    p_raw_item_id,
    p_analysis->>'stance',
    array(select jsonb_array_elements_text(p_analysis->'framing_tags')),
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
    p_raw_item_id, item.claim_text, item.claim_type,
    item.checkability, item.importance_score
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
