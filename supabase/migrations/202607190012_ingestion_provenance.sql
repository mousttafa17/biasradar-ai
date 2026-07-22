-- Preserve provider identifiers, licensing notes, and required attribution for
-- broader official, transcript, interview, and social ingestion.

alter table public.raw_items
  add column external_id text,
  add column content_license text,
  add column attribution text,
  add constraint raw_items_external_id_not_blank
    check (external_id is null or length(trim(external_id)) > 0),
  add constraint raw_items_content_license_not_blank
    check (content_license is null or length(trim(content_license)) > 0),
  add constraint raw_items_attribution_not_blank
    check (attribution is null or length(trim(attribution)) > 0);

create index raw_items_provider_external_id_idx
  on public.raw_items (ingestion_provider, external_id)
  where external_id is not null;
