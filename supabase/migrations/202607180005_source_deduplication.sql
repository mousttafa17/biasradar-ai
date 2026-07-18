-- Normalize publishers and persist deterministic content-chain metadata.
-- No raw item is deleted; aggregation uses content groups as independence units.

-- Preserve legacy source rows while making their normalization keys explicit.
update public.sources
set domain = 'legacy-' || id::text || '.invalid'
where domain is null or btrim(domain) = '';

update public.sources
set source_type = 'unknown'
where source_type is null or btrim(source_type) = '';

alter table public.sources
  alter column domain set not null,
  alter column source_type set not null,
  add constraint sources_domain_type_unique unique (domain, source_type),
  add constraint sources_reliability_range check (reliability_score between 0 and 1);

alter table public.raw_items
  add column source_id uuid references public.sources(id),
  add column canonical_url text,
  add column normalized_domain text,
  add column content_hash text,
  add column content_simhash text,
  add column content_group_id text,
  add column is_group_origin boolean,
  add column deduplicated_at timestamp with time zone,
  add constraint raw_items_content_hash_format check (
    content_hash is null or content_hash ~ '^[0-9a-f]{64}$'
  ),
  add constraint raw_items_content_simhash_format check (
    content_simhash is null or content_simhash ~ '^[0-9a-f]{16}$'
  ),
  add constraint raw_items_content_group_format check (
    content_group_id is null or content_group_id ~ '^[0-9a-f]{32}$'
  );

create index raw_items_source_id_idx on public.raw_items (source_id);
create index raw_items_content_hash_idx on public.raw_items (content_hash);
create index raw_items_content_group_idx on public.raw_items (content_group_id);
create index raw_items_topic_deduplicated_idx
  on public.raw_items (topic_id, deduplicated_at);

alter table public.topic_reports
  add column independent_content_groups integer,
  add column syndicated_items integer,
  add column deduplicated_items integer,
  add constraint topic_reports_independent_groups_nonnegative
    check (independent_content_groups >= 0),
  add constraint topic_reports_syndicated_items_nonnegative
    check (syndicated_items >= 0),
  add constraint topic_reports_deduplicated_items_nonnegative
    check (deduplicated_items >= 0);
