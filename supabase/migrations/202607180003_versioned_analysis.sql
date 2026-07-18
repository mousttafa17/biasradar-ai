-- Preserve analysis history, link claims to exact versions, and atomically supersede
-- the current result. Apply after 202607180002_topic_aggregation.sql.

alter table public.analysis
  add column analysis_version integer not null default 1,
  add column prompt_version text not null default 'legacy-v1',
  add column model_id text not null default 'unknown',
  add column is_current boolean not null default true,
  add column superseded_at timestamp with time zone,
  add constraint analysis_version_positive check (analysis_version > 0),
  add constraint analysis_prompt_version_not_blank check (length(prompt_version) > 0),
  add constraint analysis_model_id_not_blank check (length(model_id) > 0);

alter table public.analysis drop constraint analysis_raw_item_unique;
create unique index analysis_one_current_per_item_idx
  on public.analysis (raw_item_id)
  where is_current;
create unique index analysis_item_version_unique_idx
  on public.analysis (raw_item_id, analysis_version);
create index analysis_current_prompt_model_idx
  on public.analysis (prompt_version, model_id)
  where is_current;

alter table public.claims add column analysis_id uuid;
update public.claims as claim
set analysis_id = current_analysis.id
from public.analysis as current_analysis
where current_analysis.raw_item_id = claim.raw_item_id
  and current_analysis.is_current
  and claim.analysis_id is null;

alter table public.claims
  alter column analysis_id set not null,
  add constraint claims_analysis_id_fkey
    foreign key (analysis_id) references public.analysis(id) on delete cascade;
create index claims_analysis_id_idx on public.claims (analysis_id);

drop function public.save_article_analysis(uuid, jsonb, jsonb, text);

create function public.save_article_analysis(
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

  select coalesce(max(analysis_version), 0) + 1
  into v_next_version
  from public.analysis
  where raw_item_id = p_raw_item_id;

  update public.analysis
  set is_current = false, superseded_at = now()
  where raw_item_id = p_raw_item_id and is_current;

  insert into public.analysis (
    raw_item_id, analysis_version, prompt_version, model_id, is_current,
    stance, framing_tags, stance_confidence, bias_direction, bias_score,
    loaded_language_score, one_sidedness_score, evidence_quality_score,
    emotionality_score, missing_counterarguments, loaded_terms, summary, reasoning
  ) values (
    p_raw_item_id,
    v_next_version,
    p_prompt_version,
    p_model_id,
    true,
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
