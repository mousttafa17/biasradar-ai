import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ReportDashboard } from "@/components/report-dashboard";
import {
  loadFootballReport,
  ReportNotFoundError,
} from "@/lib/report-loader";

type Props = {
  params: Promise<{ topicId: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { topicId } = await params;
  return {
    title: topicId === "demo" ? "Disputed semifinal penalty" : "Topic report",
    description:
      "BiasRadar Football narrative report for the Argentina v England semifinal controversy.",
  };
}

export default async function TopicReportPage({ params }: Props) {
  const { topicId } = await params;
  const report = await loadReportOrNotFound(topicId);
  return <ReportDashboard fixture={report} topicId={topicId} />;
}

async function loadReportOrNotFound(topicId: string) {
  try {
    return await loadFootballReport(topicId);
  } catch (error) {
    if (error instanceof ReportNotFoundError) {
      notFound();
    }
    throw error;
  }
}
