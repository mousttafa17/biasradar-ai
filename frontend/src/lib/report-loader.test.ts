import { describe, expect, it, vi } from "vitest";

import { footballReportFixture } from "@/lib/fixtures/football-report";
import {
  loadFootballReport,
  ReportNotFoundError,
} from "@/lib/report-loader";

const topicId = footballReportFixture.overview.topic.id;

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fixtureFetcher() {
  return vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url.includes("/overview")) {
      return jsonResponse(footballReportFixture.overview);
    }
    if (url.includes("/incidents")) {
      return jsonResponse(footballReportFixture.incidents);
    }
    if (url.includes("/narratives")) {
      return jsonResponse(footballReportFixture.narratives);
    }
    if (url.includes("/timeline")) {
      return jsonResponse(footballReportFixture.timeline);
    }
    return jsonResponse({}, 404);
  });
}

describe("loadFootballReport", () => {
  it("keeps the demo route fixture-backed without a network request", async () => {
    const fetcher = fixtureFetcher();

    const report = await loadFootballReport("demo", { fetcher });

    expect(report).toBe(footballReportFixture);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("fetches and validates all four report endpoints", async () => {
    const fetcher = fixtureFetcher();

    const report = await loadFootballReport(topicId, {
      apiUrl: "https://api.biasradar.example",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledTimes(4);
    expect(fetcher.mock.calls.map(([input]) => String(input))).toEqual([
      `https://api.biasradar.example/topics/${topicId}/overview?days=30`,
      `https://api.biasradar.example/topics/${topicId}/incidents?days=30&limit=500`,
      `https://api.biasradar.example/topics/${topicId}/narratives?days=365&limit=100`,
      `https://api.biasradar.example/topics/${topicId}/timeline?days=365&limit=365`,
    ]);
    expect(report.overview.topic.name).toContain("disputed semifinal penalty");
    expect(report.incidents.items).toHaveLength(3);
  });

  it("maps missing topics and reports to a not-found error", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => jsonResponse({}, 404));

    await expect(
      loadFootballReport(topicId, {
        apiUrl: "https://api.biasradar.example",
        fetcher,
      }),
    ).rejects.toBeInstanceOf(ReportNotFoundError);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("rejects malformed public API data", async () => {
    const fetcher = fixtureFetcher();
    fetcher.mockImplementation(async (input) => {
      if (String(input).includes("/overview")) {
        return jsonResponse({ topic: { id: topicId }, internal_reasoning: "secret" });
      }
      if (String(input).includes("/incidents")) {
        return jsonResponse(footballReportFixture.incidents);
      }
      if (String(input).includes("/narratives")) {
        return jsonResponse(footballReportFixture.narratives);
      }
      return jsonResponse(footballReportFixture.timeline);
    });

    await expect(
      loadFootballReport(topicId, {
        apiUrl: "https://api.biasradar.example",
        fetcher,
      }),
    ).rejects.toMatchObject({
      reason: "invalid_response",
    });
  });

  it("rejects invalid topic identifiers without contacting the API", async () => {
    const fetcher = fixtureFetcher();

    await expect(
      loadFootballReport("not-a-topic-id", { fetcher }),
    ).rejects.toBeInstanceOf(ReportNotFoundError);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects responses belonging to a different topic", async () => {
    const fetcher = fixtureFetcher();
    fetcher.mockImplementation(async (input) => {
      if (String(input).includes("/timeline")) {
        return jsonResponse({
          ...footballReportFixture.timeline,
          topic_id: "55555555-5555-4555-8555-555555555555",
        });
      }
      if (String(input).includes("/overview")) {
        return jsonResponse(footballReportFixture.overview);
      }
      if (String(input).includes("/incidents")) {
        return jsonResponse(footballReportFixture.incidents);
      }
      return jsonResponse(footballReportFixture.narratives);
    });

    await expect(
      loadFootballReport(topicId, {
        apiUrl: "https://api.biasradar.example",
        fetcher,
      }),
    ).rejects.toMatchObject({
      reason: "invalid_response",
    });
  });
});
