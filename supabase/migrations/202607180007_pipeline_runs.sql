-- Auditable, idempotent topic pipeline runs and report provenance.
-- Apply after 202607180006_multichannel_ingestion.sql.

create table public.pipeline_runs (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid not null references public.topics(id),
  idempotency_key text not null unique,
  status text not null default 'running' check (
    status in ('running', 'completed', 'failed')
  ),
  period_start timestamp with time zone not null,
  period_end timestamp with time zone not null,
  prompt_version text not null,
  model_id text not null,
  counters jsonb not null default '{}'::jsonb check (
    jsonb_typeof(counters) = 'object'
  ),
  provider_errors jsonb not null default '[]'::jsonb check (
    jsonb_typeof(provider_errors) = 'array'
  ),
  error_summary text,
  report_id uuid references public.topic_reports(id),
  started_at timestamp with time zone not null default now(),
  heartbeat_at timestamp with time zone not null default now(),
  finished_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  check (period_end > period_start),
  check (error_summary is null or length(error_summary) <= 500)
);

create unique index pipeline_runs_one_active_topic_idx
  on public.pipeline_runs (topic_id)
  where status = 'running';

create index pipeline_runs_topic_started_idx
  on public.pipeline_runs (topic_id, started_at desc);

alter table public.topic_reports
  add column pipeline_run_id uuid unique references public.pipeline_runs(id);

alter table public.pipeline_runs enable row level security;
revoke all on table public.pipeline_runs from anon, authenticated;

create or replace function public.begin_pipeline_run(
  p_topic_id uuid,
  p_idempotency_key text,
  p_period_start timestamp with time zone,
  p_period_end timestamp with time zone,
  p_prompt_version text,
  p_model_id text
)
returns public.pipeline_runs
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.pipeline_runs;
begin
  select * into v_run
  from public.pipeline_runs
  where idempotency_key = p_idempotency_key
  for update;

  if found then
    if v_run.status = 'completed' then
      return v_run;
    end if;
    if v_run.status = 'running' then
      if v_run.heartbeat_at > now() - interval '30 minutes' then
        raise exception 'pipeline run is already active' using errcode = '55000';
      end if;
    end if;
    update public.pipeline_runs
    set status = 'running', counters = '{}'::jsonb, provider_errors = '[]'::jsonb,
        error_summary = null, report_id = null, started_at = now(),
        heartbeat_at = now(), finished_at = null
    where id = v_run.id
    returning * into v_run;
    return v_run;
  end if;

  insert into public.pipeline_runs (
    topic_id, idempotency_key, period_start, period_end, prompt_version, model_id
  ) values (
    p_topic_id, p_idempotency_key, p_period_start, p_period_end,
    p_prompt_version, p_model_id
  ) returning * into v_run;
  return v_run;
exception
  when unique_violation then
    raise exception 'another pipeline run is active for this topic'
      using errcode = '55000';
end;
$$;

revoke execute on function public.begin_pipeline_run(
  uuid, text, timestamp with time zone, timestamp with time zone, text, text
) from public, anon, authenticated;
grant execute on function public.begin_pipeline_run(
  uuid, text, timestamp with time zone, timestamp with time zone, text, text
) to service_role;
