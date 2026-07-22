export type ConfidenceLevel = "low" | "moderate" | "high";

export interface TopicSummary {
  id: string;
  name: string;
  status: string;
  keywords: string[];
}

export interface ConsensusResult {
  incident_ref: string;
  source_group: string;
  status: string;
  leading_position: string | null;
  leading_percent: number | null;
  position_distribution: Record<string, number>;
  extracted_opinions: number;
  independent_opinions: number;
  duplicate_mentions: number;
  average_source_quality: number;
  confidence: number;
  source_roles: Record<string, number>;
  summary: string;
  limitations: string[];
}

export interface FootballReportSummary {
  analyzed_items: number;
  stance_distribution: Record<string, number>;
  stance_counts: Record<string, number>;
  controversy_type_counts: Record<string, number>;
  content_mode_counts: Record<string, number>;
  framing_tag_counts: Record<string, number>;
  teams: Record<string, number>;
  referees: Record<string, number>;
  federations: Record<string, number>;
  attributed_expert_opinions: number;
  consensus_results: ConsensusResult[];
}

export interface TopicOverview {
  topic: TopicSummary;
  domain_profile: string;
  report_id: string;
  period_start: string;
  period_end: string;
  total_items: number;
  source_count: number;
  independent_content_groups: number;
  syndicated_items: number;
  channel_counts: Record<string, number>;
  stance_distribution: {
    pro_subject: number;
    anti_subject: number;
    neutral: number;
    mixed: number;
    unclear: number;
  };
  directional_pro_percent: number | null;
  directional_anti_percent: number | null;
  overall_bias_score: number;
  confidence_score: number;
  confidence_level: ConfidenceLevel;
  repeated_claim_count: number;
  fact_check_summary: Record<string, number>;
  verified_findings: string[];
  football_summary: FootballReportSummary | null;
  methodology: string;
  limitations: string[];
  summary: string;
}

export interface VisualizationMetric {
  label: string;
  percentage: number;
  item_count: number;
  confidence: number;
  trend: number | null;
}

export interface NarrativeHistoryPoint {
  report_id: string;
  timestamp: string;
  metrics: VisualizationMetric[];
}

export interface NarrativeResponse {
  topic_id: string;
  period_start: string;
  period_end: string;
  metrics: VisualizationMetric[];
  controversy_type_counts: Record<string, number>;
  content_mode_counts: Record<string, number>;
  framing_tag_counts: Record<string, number>;
  consensus: ConsensusResult[];
  history: NarrativeHistoryPoint[];
}

export interface IncidentView {
  incident_id: string;
  controversy_type: string;
  description: string;
  match_minute: number | null;
  on_field_decision: string | null;
  review_outcome: string | null;
  item_count: number;
  source_count: number;
  independent_content_groups: number;
  syndicated_items: number;
  channel_counts: Record<string, number>;
  consensus: ConsensusResult[];
}

export interface IncidentListResponse {
  topic_id: string;
  period_start: string;
  period_end: string;
  items: IncidentView[];
  limitations: string[];
}

export interface TimelinePoint {
  report_id: string;
  timestamp: string;
  toward_percent: number | null;
  against_percent: number | null;
  bias_score: number;
  confidence: number;
  independent_content_groups: number;
  channel_counts: Record<string, number>;
}

export interface TimelineResponse {
  topic_id: string;
  points: TimelinePoint[];
}

export interface FootballReportFixture {
  overview: TopicOverview;
  incidents: IncidentListResponse;
  narratives: NarrativeResponse;
  timeline: TimelineResponse;
}
