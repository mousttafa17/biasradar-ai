import { z } from "zod";

const recordOfNumbers = z.record(z.string(), z.number());
const isoDate = z.string().datetime({ offset: true });
const uuid = z.string().uuid();

export const consensusResultSchema = z.strictObject({
  incident_ref: z.string(),
  source_group: z.string(),
  status: z.string(),
  leading_position: z.string().nullable(),
  leading_percent: z.number().min(0).max(100).nullable(),
  position_distribution: recordOfNumbers,
  extracted_opinions: z.number().int().nonnegative(),
  independent_opinions: z.number().int().nonnegative(),
  duplicate_mentions: z.number().int().nonnegative(),
  average_source_quality: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
  source_roles: recordOfNumbers,
  summary: z.string(),
  limitations: z.array(z.string()),
});

const footballSummarySchema = z.strictObject({
  analyzed_items: z.number().int().nonnegative(),
  stance_distribution: recordOfNumbers,
  stance_counts: recordOfNumbers,
  controversy_type_counts: recordOfNumbers,
  content_mode_counts: recordOfNumbers,
  framing_tag_counts: recordOfNumbers,
  teams: recordOfNumbers,
  referees: recordOfNumbers,
  federations: recordOfNumbers,
  attributed_expert_opinions: z.number().int().nonnegative(),
  consensus_results: z.array(consensusResultSchema),
});

export const topicOverviewSchema = z.strictObject({
  topic: z.strictObject({
    id: uuid,
    name: z.string(),
    status: z.string(),
    keywords: z.array(z.string()),
  }),
  domain_profile: z.string(),
  report_id: uuid,
  period_start: isoDate,
  period_end: isoDate,
  total_items: z.number().int().nonnegative(),
  source_count: z.number().int().nonnegative(),
  independent_content_groups: z.number().int().nonnegative(),
  syndicated_items: z.number().int().nonnegative(),
  channel_counts: recordOfNumbers,
  stance_distribution: z.strictObject({
    pro_subject: z.number().min(0).max(100),
    anti_subject: z.number().min(0).max(100),
    neutral: z.number().min(0).max(100),
    mixed: z.number().min(0).max(100),
    unclear: z.number().min(0).max(100),
  }),
  directional_pro_percent: z.number().min(0).max(100).nullable(),
  directional_anti_percent: z.number().min(0).max(100).nullable(),
  overall_bias_score: z.number().min(-100).max(100),
  confidence_score: z.number().min(0).max(1),
  confidence_level: z.enum(["low", "moderate", "high"]),
  repeated_claim_count: z.number().int().nonnegative(),
  fact_check_summary: recordOfNumbers,
  verified_findings: z.array(z.string()),
  football_summary: footballSummarySchema.nullable(),
  methodology: z.string(),
  limitations: z.array(z.string()),
  summary: z.string(),
});

export const visualizationMetricSchema = z.strictObject({
  label: z.string(),
  percentage: z.number().min(0).max(100),
  item_count: z.number().int().nonnegative(),
  confidence: z.number().min(0).max(1),
  trend: z.number().nullable(),
});

export const narrativeResponseSchema = z.strictObject({
  topic_id: uuid,
  period_start: isoDate,
  period_end: isoDate,
  metrics: z.array(visualizationMetricSchema),
  controversy_type_counts: recordOfNumbers,
  content_mode_counts: recordOfNumbers,
  framing_tag_counts: recordOfNumbers,
  consensus: z.array(consensusResultSchema),
  history: z.array(
    z.strictObject({
      report_id: uuid,
      timestamp: isoDate,
      metrics: z.array(visualizationMetricSchema),
    }),
  ),
});

export const incidentListResponseSchema = z.strictObject({
  topic_id: uuid,
  period_start: isoDate,
  period_end: isoDate,
  items: z.array(
    z.strictObject({
      incident_id: z.string(),
      controversy_type: z.string(),
      description: z.string(),
      match_minute: z.number().int().min(0).max(130).nullable(),
      on_field_decision: z.string().nullable(),
      review_outcome: z.string().nullable(),
      item_count: z.number().int().positive(),
      source_count: z.number().int().positive(),
      independent_content_groups: z.number().int().positive(),
      syndicated_items: z.number().int().nonnegative(),
      channel_counts: recordOfNumbers,
      consensus: z.array(consensusResultSchema),
    }),
  ),
  limitations: z.array(z.string()),
});

export const timelineResponseSchema = z.strictObject({
  topic_id: uuid,
  points: z.array(
    z.strictObject({
      report_id: uuid,
      timestamp: isoDate,
      toward_percent: z.number().min(0).max(100).nullable(),
      against_percent: z.number().min(0).max(100).nullable(),
      bias_score: z.number().min(-100).max(100),
      confidence: z.number().min(0).max(1),
      independent_content_groups: z.number().int().nonnegative(),
      channel_counts: recordOfNumbers,
    }),
  ),
});
