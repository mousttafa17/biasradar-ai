-- Store reproducible provider evidence for immutable, version-linked claims.
-- Apply after 202607180003_versioned_analysis.sql.

alter table public.claim_checks
  add column provider text not null default 'google_fact_check_tools',
  add column method_version text not null default 'google-claim-search-v1',
  add column matched_claim_text text,
  add column match_score numeric,
  add column evidence_data jsonb not null default '{}'::jsonb,
  add constraint claim_checks_claim_unique unique (claim_id),
  add constraint claim_checks_verdict_valid check (
    verdict in (
      'supported', 'contradicted', 'unverified', 'misleading',
      'opinion', 'needs_human_review'
    )
  ),
  add constraint claim_checks_confidence_range check (confidence between 0 and 1),
  add constraint claim_checks_match_score_range check (match_score between 0 and 1),
  add constraint claim_checks_provider_not_blank check (length(provider) > 0),
  add constraint claim_checks_method_version_not_blank
    check (length(method_version) > 0);

create index claim_checks_verdict_idx on public.claim_checks (verdict);
create index claim_checks_checked_at_idx on public.claim_checks (checked_at desc);
