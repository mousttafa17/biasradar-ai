-- Persist generic domain identity and validated domain payloads on every versioned
-- article analysis. Apply after 202607190010_evidence_review.sql.

alter table public.analysis
  add column domain_profile text not null default 'generic-v1',
  add column domain_analysis jsonb not null default '{}'::jsonb,
  add constraint analysis_domain_profile_not_blank
    check (length(trim(domain_profile)) > 0),
  add constraint analysis_domain_analysis_object
    check (jsonb_typeof(domain_analysis) = 'object');

create index analysis_current_domain_profile_idx
  on public.analysis (domain_profile)
  where is_current;

create or replace function public.save_article_analysis(
  p_raw_item_id uuid,
  p_analysis jsonb,
  p_claims jsonb,
  p_cleaned_text text,
  p_model_id text,
  p_prompt_version text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_analysis_id uuid;
  v_next_version integer;
  v_domain_profile text;
  v_domain_analysis jsonb;
begin
  if not exists (
    select 1 from public.raw_items where id = p_raw_item_id for update
  ) then
    raise exception 'raw item does not exist' using errcode = '23503';
  end if;

  if nullif(trim(p_model_id), '') is null
     or nullif(trim(p_prompt_version), '') is null then
    raise exception 'model and prompt versions are required' using errcode = '22023';
  end if;

  v_domain_profile := coalesce(nullif(trim(p_analysis->>'domain_profile'), ''), 'generic-v1');
  v_domain_analysis := coalesce(p_analysis->'domain_analysis', '{}'::jsonb);
  if jsonb_typeof(v_domain_analysis) <> 'object' then
    raise exception 'domain_analysis must be a JSON object' using errcode = '22023';
  end if;

  select coalesce(max(analysis_version), 0) + 1
  into v_next_version
  from public.analysis
  where raw_item_id = p_raw_item_id;

  update public.analysis
  set is_current = false, superseded_at = now()
  where raw_item_id = p_raw_item_id and is_current;

  insert into public.analysis (
    raw_item_id, analysis_version, prompt_version, model_id, is_current,
    domain_profile, domain_analysis, stance, framing_tags, stance_confidence,
    bias_direction, bias_score, loaded_language_score, one_sidedness_score,
    evidence_quality_score, emotionality_score, missing_counterarguments,
    loaded_terms, summary, reasoning
  ) values (
    p_raw_item_id,
    v_next_version,
    p_prompt_version,
    p_model_id,
    true,
    v_domain_profile,
    v_domain_analysis,
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
    analysis_id, raw_item_id, claim_text, claim_type,
    checkability, importance_score
  )
  select
    v_analysis_id,
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

revoke execute on function public.save_article_analysis(
  uuid, jsonb, jsonb, text, text, text
) from public, anon, authenticated;
grant execute on function public.save_article_analysis(
  uuid, jsonb, jsonb, text, text, text
) to service_role;
