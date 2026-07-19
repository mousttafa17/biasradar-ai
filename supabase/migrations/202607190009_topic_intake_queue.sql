-- Authenticated intake ownership, persistent rate limiting, and worker leases.
-- Apply after 202607190008_topic_viability.sql.

alter table public.topic_submissions
  drop constraint topic_submissions_query_hash_key,
  add column user_id uuid references auth.users(id) on delete set null,
  add column idempotency_key text,
  add column attempt_count integer not null default 0 check (attempt_count between 0 and 3),
  add column lease_expires_at timestamp with time zone,
  add column next_attempt_at timestamp with time zone,
  add column updated_at timestamp with time zone not null default now(),
  add constraint topic_submissions_idempotency_length check (
    idempotency_key is null or length(idempotency_key) between 8 and 200
  );

create unique index topic_submissions_user_query_unique
  on public.topic_submissions (user_id, query_hash) where user_id is not null;
create unique index topic_submissions_cli_query_unique
  on public.topic_submissions (query_hash) where user_id is null;
create unique index topic_submissions_user_idempotency_unique
  on public.topic_submissions (user_id, idempotency_key)
  where user_id is not null and idempotency_key is not null;
create index topic_submissions_worker_queue_idx
  on public.topic_submissions (status, next_attempt_at, created_at);

create table public.topic_intake_rate_limits (
  identity_hash text not null,
  window_start timestamp with time zone not null,
  request_count integer not null default 0 check (request_count >= 0),
  primary key (identity_hash, window_start)
);
alter table public.topic_intake_rate_limits enable row level security;
revoke all on table public.topic_intake_rate_limits from anon, authenticated;

create or replace function public.consume_topic_intake_rate_limit(
  p_identity_hash text,
  p_limit integer
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
  v_window timestamp with time zone := date_trunc('hour', now());
begin
  if p_limit < 1 or p_limit > 100 then
    raise exception 'invalid rate limit' using errcode = '22023';
  end if;
  delete from public.topic_intake_rate_limits
  where identity_hash = p_identity_hash
    and window_start < v_window - interval '7 days';
  insert into public.topic_intake_rate_limits (
    identity_hash, window_start, request_count
  ) values (p_identity_hash, v_window, 1)
  on conflict (identity_hash, window_start) do update
    set request_count = public.topic_intake_rate_limits.request_count + 1
  returning request_count into v_count;
  return v_count <= p_limit;
end;
$$;

create or replace function public.claim_topic_submissions(p_limit integer)
returns setof public.topic_submissions
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_limit < 1 or p_limit > 50 then
    raise exception 'invalid claim limit' using errcode = '22023';
  end if;
  return query
  with candidates as (
    select id from public.topic_submissions
    where (
      status = 'submitted'
      or (status = 'assessing' and lease_expires_at < now())
    )
      and coalesce(next_attempt_at, now()) <= now()
      and attempt_count < 3
    order by created_at
    for update skip locked
    limit p_limit
  )
  update public.topic_submissions as submission
  set status = 'assessing',
      attempt_count = attempt_count + 1,
      lease_expires_at = now() + interval '30 minutes',
      updated_at = now()
  from candidates
  where submission.id = candidates.id
  returning submission.*;
end;
$$;

revoke execute on function public.consume_topic_intake_rate_limit(text, integer)
  from public, anon, authenticated;
grant execute on function public.consume_topic_intake_rate_limit(text, integer)
  to service_role;
revoke execute on function public.claim_topic_submissions(integer)
  from public, anon, authenticated;
grant execute on function public.claim_topic_submissions(integer)
  to service_role;
