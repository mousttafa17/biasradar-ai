-- Durable daily topic schedules and worker liveness for horizontally safe workers.

create table public.topic_schedules (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid not null unique references public.topics(id) on delete cascade,
  enabled boolean not null default true,
  interval_minutes integer not null default 1440 check (interval_minutes between 1440 and 10080),
  lookback_days integer not null default 30 check (lookback_days between 1 and 3650),
  news_limit integer not null default 20 check (news_limit between 1 and 100),
  rss_limit integer not null default 20 check (rss_limit between 1 and 100),
  next_run_at timestamp with time zone not null default now(),
  lease_expires_at timestamp with time zone,
  last_started_at timestamp with time zone,
  last_completed_at timestamp with time zone,
  last_status text check (last_status in ('running', 'completed', 'failed')),
  last_error text check (last_error is null or length(last_error) <= 500),
  consecutive_failures integer not null default 0 check (consecutive_failures >= 0),
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create index topic_schedules_due_idx
  on public.topic_schedules (enabled, next_run_at)
  where enabled;

create table public.worker_instances (
  worker_id text primary key check (length(worker_id) between 1 and 200),
  started_at timestamp with time zone not null default now(),
  heartbeat_at timestamp with time zone not null default now(),
  metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object')
);

alter table public.topic_schedules enable row level security;
alter table public.worker_instances enable row level security;
revoke all on table public.topic_schedules, public.worker_instances from anon, authenticated;

create function public.claim_due_topic_schedules(p_limit integer)
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
  )
  update public.topic_schedules as schedule
  set lease_expires_at = now() + interval '2 hours',
      last_started_at = now(), last_status = 'running',
      last_error = null, updated_at = now()
  from candidates where schedule.id = candidates.id
  returning schedule.*;
end;
$$;

create function public.finish_topic_schedule(
  p_schedule_id uuid, p_succeeded boolean, p_error text default null
) returns void
language plpgsql security definer set search_path = '' as $$
begin
  update public.topic_schedules
  set lease_expires_at = null,
      last_status = case when p_succeeded then 'completed' else 'failed' end,
      last_error = case when p_succeeded then null else left(coalesce(p_error, 'worker failure'), 500) end,
      last_completed_at = case when p_succeeded then now() else last_completed_at end,
      consecutive_failures = case when p_succeeded then 0 else consecutive_failures + 1 end,
      next_run_at = case
        when p_succeeded then now() + make_interval(mins => interval_minutes)
        else now() + make_interval(mins => least(60, 5 * (consecutive_failures + 1)))
      end,
      updated_at = now()
  where id = p_schedule_id;
end;
$$;

create function public.heartbeat_worker(p_worker_id text, p_metadata jsonb)
returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.worker_instances (worker_id, metadata)
  values (p_worker_id, coalesce(p_metadata, '{}'::jsonb))
  on conflict (worker_id) do update
    set heartbeat_at = now(), metadata = excluded.metadata;
  delete from public.worker_instances where heartbeat_at < now() - interval '7 days';
end;
$$;

revoke execute on function public.claim_due_topic_schedules(integer) from public, anon, authenticated;
revoke execute on function public.finish_topic_schedule(uuid, boolean, text) from public, anon, authenticated;
revoke execute on function public.heartbeat_worker(text, jsonb) from public, anon, authenticated;
grant execute on function public.claim_due_topic_schedules(integer) to service_role;
grant execute on function public.finish_topic_schedule(uuid, boolean, text) to service_role;
grant execute on function public.heartbeat_worker(text, jsonb) to service_role;
