import type { Metadata } from "next";

import { ReportDashboard } from "@/components/report-dashboard";
import { footballReportFixture } from "@/lib/fixtures/football-report";

type Props = {
  params: Promise<{ topicId: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  await params;
  return {
    title: "Disputed semifinal penalty",
    description:
      "BiasRadar Football narrative report for the Argentina v England semifinal controversy.",
  };
}

export default async function TopicReportPage({ params }: Props) {
  const { topicId } = await params;
  return <ReportDashboard fixture={footballReportFixture} topicId={topicId} />;
}
