-- Persist provider provenance and optional channel-specific engagement metadata.
-- Apply after 202607180005_source_deduplication.sql.

alter table public.raw_items
  add column ingestion_provider text not null default 'legacy',
  add column engagement_data jsonb not null default '{}'::jsonb,
  add constraint raw_items_ingestion_provider_nonempty check (
    btrim(ingestion_provider) <> ''
  ),
  add constraint raw_items_engagement_object check (
    jsonb_typeof(engagement_data) = 'object'
  );

create index raw_items_topic_channel_idx
  on public.raw_items (topic_id, source_type, fetched_at desc);
