import type { z } from "zod";

import type {
  FootballReportFixture,
  IncidentListResponse,
  NarrativeResponse,
  TimelineResponse,
  TopicOverview,
} from "@/lib/api-types";
import { getPublicApiUrl } from "@/lib/config";
import { footballReportFixture } from "@/lib/fixtures/football-report";
import {
  incidentListResponseSchema,
  narrativeResponseSchema,
  timelineResponseSchema,
  topicOverviewSchema,
} from "@/lib/report-schemas";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Fetcher = typeof fetch;

export class ReportNotFoundError extends Error {
  constructor() {
    super("report not found");
    this.name = "ReportNotFoundError";
  }
}

export class ReportApiError extends Error {
  constructor(public readonly reason: "upstream" | "invalid_response") {
    super("report service unavailable");
    this.name = "ReportApiError";
  }
}

async function requestJson<T>(
  url: string,
  schema: z.ZodType<T>,
  fetcher: Fetcher,
): Promise<T> {
  let response: Response;
  try {
    response = await fetcher(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new ReportApiError("upstream");
  }

  if (response.status === 404) {
    throw new ReportNotFoundError();
  }
  if (!response.ok) {
    throw new ReportApiError("upstream");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ReportApiError("invalid_response");
  }
  const result = schema.safeParse(payload);
  if (!result.success) {
    throw new ReportApiError("invalid_response");
  }
  return result.data;
}

export async function loadFootballReport(
  topicId: string,
  options: { apiUrl?: string; fetcher?: Fetcher } = {},
): Promise<FootballReportFixture> {
  if (topicId === "demo") {
    return footballReportFixture;
  }
  if (!UUID_PATTERN.test(topicId)) {
    throw new ReportNotFoundError();
  }

  const apiUrl = (options.apiUrl ?? getPublicApiUrl()).replace(/\/$/, "");
  const fetcher = options.fetcher ?? fetch;
  const topicRoot = `${apiUrl}/topics/${encodeURIComponent(topicId)}`;

  const [overview, incidents, narratives, timeline] = await Promise.all([
    requestJson<TopicOverview>(
      `${topicRoot}/overview?days=30`,
      topicOverviewSchema,
      fetcher,
    ),
    requestJson<IncidentListResponse>(
      `${topicRoot}/incidents?days=30&limit=500`,
      incidentListResponseSchema,
      fetcher,
    ),
    requestJson<NarrativeResponse>(
      `${topicRoot}/narratives?days=365&limit=100`,
      narrativeResponseSchema,
      fetcher,
    ),
    requestJson<TimelineResponse>(
      `${topicRoot}/timeline?days=365&limit=365`,
      timelineResponseSchema,
      fetcher,
    ),
  ]);

  if (
    overview.topic.id !== topicId ||
    incidents.topic_id !== topicId ||
    narratives.topic_id !== topicId ||
    timeline.topic_id !== topicId
  ) {
    throw new ReportApiError("invalid_response");
  }

  return { overview, incidents, narratives, timeline };
}
