-- Connect accepted topic intake to its first scheduled analysis and expose a
-- frontend-ready submission lifecycle. Apply after worker scheduling migration 013.

alter table public.topic_schedules
  add column initial_submission_id uuid unique
    references public.topic_submissions(id) on delete set null;

alter table public.topic_submissions
  drop constraint topic_submissions_status_check;

update public.topic_submissions
set status = 'assessing_viability'
where status = 'assessing';

update public.topic_submissions as submission
set status = case
  when exists (
    select 1 from public.topic_reports as report
    where report.topic_id = submission.topic_id
  ) then 'report_ready'
  else 'queued_for_analysis'
end
where status = 'accepted' and topic_id is not null;

alter table public.topic_submissions
  add constraint topic_submissions_status_check check (
    status in (
      'submitted', 'assessing_viability', 'needs_clarification',
      'insufficient_coverage', 'too_broad', 'too_narrow', 'unsafe',
      'duplicate_topic', 'queued_for_analysis', 'analyzing',
      'report_ready', 'failed'
    )
  );

-- Existing accepted topics without reports should become runnable immediately.
insert into public.topic_schedules (
  topic_id, initial_submission_id, next_run_at
)
select submission.topic_id, submission.id, now()
from public.topic_submissions as submission
where submission.status = 'queued_for_analysis'
  and submission.topic_id is not null
on conflict (topic_id) do update
set initial_submission_id = coalesce(
      public.topic_schedules.initial_submission_id,
      excluded.initial_submission_id
    ),
    next_run_at = least(public.topic_schedules.next_run_at, excluded.next_run_at),
    enabled = true,
    updated_at = now();

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
  v_submission_status text;
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
  if v_existing_status in (
    'queued_for_analysis', 'analyzing', 'report_ready', 'duplicate_topic'
  ) and v_topic_id is not null then
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
    v_submission_status := 'queued_for_analysis';
  elsif p_status = 'duplicate_topic' then
    v_topic_id := p_duplicate_topic_id;
    v_submission_status := 'duplicate_topic';
  else
    v_submission_status := p_status;
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
  set status = v_submission_status,
      topic_id = v_topic_id,
      assessed_at = now(),
      lease_expires_at = null,
      next_attempt_at = null,
      updated_at = now()
  where id = p_submission_id;

  if p_status = 'accepted' then
    insert into public.topic_schedules (
      topic_id, initial_submission_id, next_run_at
    ) values (
      v_topic_id, p_submission_id, now()
    ) on conflict (topic_id) do update set
      initial_submission_id = coalesce(
        public.topic_schedules.initial_submission_id,
        excluded.initial_submission_id
      ),
      next_run_at = least(public.topic_schedules.next_run_at, excluded.next_run_at),
      enabled = true,
      updated_at = now();
  end if;

  return v_topic_id;
end;
$$;

create or replace function public.claim_topic_submissions(p_limit integer)
returns setof public.topic_submissions
language plpgsql security definer set search_path = '' as $$
begin
  if p_limit < 1 or p_limit > 50 then
    raise exception 'invalid claim limit' using errcode = '22023';
  end if;
  return query
  with candidates as (
    select id from public.topic_submissions
    where (
      status = 'submitted'
      or (status = 'assessing_viability' and lease_expires_at < now())
    )
      and coalesce(next_attempt_at, now()) <= now()
      and attempt_count < 3
    order by created_at
    for update skip locked
    limit p_limit
  )
  update public.topic_submissions as submission
  set status = 'assessing_viability',
      attempt_count = attempt_count + 1,
      lease_expires_at = now() + interval '30 minutes',
      updated_at = now()
  from candidates
  where submission.id = candidates.id
  returning submission.*;
end;
$$;

create or replace function public.claim_due_topic_schedules(p_limit integer)
returns setof public.topic_schedules
language plpgsql security definer set search_path = '' as $$
begin
  if p_limit < 1 or p_limit > 20 then
    raise exception 'invalid schedule claim limit' using errcode = '22023';
  end if;
  return query
  with candidates as (
    select id from public.topic_schedules
    where enabled and next_run_at <= now()
      and (lease_expires_at is null or lease_expires_at < now())
    order by next_run_at
    for update skip locked
    limit p_limit
  ), claimed as (
    update public.topic_schedules as schedule
    set lease_expires_at = now() + interval '2 hours',
        last_started_at = now(),
        last_status = 'running',
        last_error = null,
        updated_at = now()
    from candidates
    where schedule.id = candidates.id
    returning schedule.*
  ), marked as (
    update public.topic_submissions as submission
    set status = 'analyzing', updated_at = now()
    from claimed
    where submission.id = claimed.initial_submission_id
      and submission.status = 'queued_for_analysis'
    returning submission.id
  )
  select claimed.*
  from claimed
  left join (select count(*) as marked_count from marked) as marker on true;
end;
$$;

create or replace function public.finish_topic_schedule(
  p_schedule_id uuid, p_succeeded boolean, p_error text default null
) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_submission_id uuid;
  v_topic_id uuid;
  v_report_exists boolean;
begin
  update public.topic_schedules
  set lease_expires_at = null,
      last_status = case when p_succeeded then 'completed' else 'failed' end,
      last_error = case
        when p_succeeded then null
        else left(coalesce(p_error, 'worker failure'), 500)
      end,
      last_completed_at = case when p_succeeded then now() else last_completed_at end,
      consecutive_failures = case
        when p_succeeded then 0 else consecutive_failures + 1
      end,
      next_run_at = case
        when p_succeeded then now() + make_interval(mins => interval_minutes)
        else now() + make_interval(
          mins => least(60, 5 * (consecutive_failures + 1))
        )
      end,
      updated_at = now()
  where id = p_schedule_id
  returning initial_submission_id, topic_id into v_submission_id, v_topic_id;

  if v_submission_id is not null then
    select exists (
      select 1 from public.topic_reports
      where topic_id = v_topic_id
    ) into v_report_exists;

    update public.topic_submissions
    set status = case
          when p_succeeded and v_report_exists then 'report_ready'
          else 'queued_for_analysis'
        end,
        updated_at = now()
    where id = v_submission_id
      and status in ('queued_for_analysis', 'analyzing');
  end if;
end;
$$;

revoke execute on function public.save_topic_viability(
  uuid, text, numeric, jsonb, jsonb, jsonb, jsonb, uuid, text, text
) from public, anon, authenticated;
grant execute on function public.save_topic_viability(
  uuid, text, numeric, jsonb, jsonb, jsonb, jsonb, uuid, text, text
) to service_role;
revoke execute on function public.claim_topic_submissions(integer)
  from public, anon, authenticated;
grant execute on function public.claim_topic_submissions(integer) to service_role;
revoke execute on function public.claim_due_topic_schedules(integer)
  from public, anon, authenticated;
grant execute on function public.claim_due_topic_schedules(integer) to service_role;
revoke execute on function public.finish_topic_schedule(uuid, boolean, text)
  from public, anon, authenticated;
grant execute on function public.finish_topic_schedule(uuid, boolean, text)
  to service_role;
