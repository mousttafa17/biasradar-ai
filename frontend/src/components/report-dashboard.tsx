"use client";

import Link from "next/link";
import { animate, motion, MotionConfig, useInView, useMotionValue, useTransform } from "motion/react";
import { useEffect, useRef, useState } from "react";

import type {
  ConsensusResult,
  FootballReportFixture,
  IncidentView,
  TimelinePoint,
  VisualizationMetric,
} from "@/lib/api-types";

const ease = [0.22, 1, 0.36, 1] as const;
const reveal = {
  hidden: { opacity: 0, y: 22 },
  visible: { opacity: 1, y: 0 },
};

export function ReportDashboard({
  fixture,
  topicId,
}: {
  fixture: FootballReportFixture;
  topicId: string;
}) {
  const { overview, incidents, narratives, timeline } = fixture;
  const [activeIncident, setActiveIncident] = useState(incidents.items[0].incident_id);
  const currentIncident =
    incidents.items.find((item) => item.incident_id === activeIncident) ?? incidents.items[0];

  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.55, ease }}>
      <main className="relative min-h-screen overflow-hidden bg-ink text-paper">
        <div className="pitch-grid pointer-events-none absolute inset-x-0 top-0 h-[48rem] opacity-20" />
        <div className="report-glow pointer-events-none absolute right-[-18rem] top-[-18rem] size-[48rem] rounded-full" />
        <ReportNav topicId={topicId} />

        <div className="relative z-10 mx-auto max-w-7xl px-5 pb-24 sm:px-8 lg:px-10">
          <ReportHero fixture={fixture} />

          {overview.confidence_level === "low" && <LowConfidenceState />}

          <section className="mt-20 grid gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Report coverage">
            <StatCard value={overview.total_items} label="Items analyzed" note="Across all channels" delay={0} />
            <StatCard value={overview.source_count} label="Distinct sources" note="Publisher identities" delay={0.06} />
            <StatCard value={overview.independent_content_groups} label="Independent groups" note="After syndication control" delay={0.12} />
            <StatCard value={overview.repeated_claim_count} label="Repeated claims" note="Cross-source clusters" delay={0.18} />
          </section>

          <NarrativeSection metrics={narratives.metrics} channels={overview.channel_counts} />
          <IncidentSection
            incidents={incidents.items}
            activeIncident={activeIncident}
            onSelect={setActiveIncident}
            currentIncident={currentIncident}
          />
          <TimelineSection points={timeline.points} />
          <ConsensusSection consensus={narratives.consensus[0]} />
          <FindingsSection fixture={fixture} />
        </div>
      </main>
    </MotionConfig>
  );
}

function ReportNav({ topicId }: { topicId: string }) {
  return (
    <header className="relative z-20 border-b border-line/80 bg-ink/60 backdrop-blur-xl">
      <nav className="mx-auto flex h-20 max-w-7xl items-center justify-between px-5 sm:px-8 lg:px-10">
        <Link href="/" className="flex items-center gap-3" aria-label="BiasRadar home">
          <span className="grid size-9 place-items-center rounded-full border border-signal/40 bg-signal/10 text-xs font-bold text-signal">
            BR
          </span>
          <span className="hidden text-sm font-semibold tracking-[0.16em] uppercase sm:block">
            BiasRadar <span className="text-muted">Football</span>
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <span className="hidden font-mono text-[0.72rem] tracking-[0.14em] text-muted uppercase md:block">
            Report {topicId.slice(0, 8)}
          </span>
          <Link
            href="/"
            className="rounded-full border border-line bg-panel/60 px-4 py-2 text-xs font-medium transition hover:border-signal/40 hover:text-signal"
          >
            New analysis <span aria-hidden>↗</span>
          </Link>
        </div>
      </nav>
    </header>
  );
}

function ReportHero({ fixture }: { fixture: FootballReportFixture }) {
  const { overview } = fixture;
  const against = overview.directional_anti_percent ?? 0;
  const toward = overview.directional_pro_percent ?? 0;

  return (
    <section className="grid gap-12 pb-4 pt-16 lg:grid-cols-[1.05fr_0.95fr] lg:items-end lg:pt-24">
      <motion.div initial="hidden" animate="visible" transition={{ staggerChildren: 0.08 }}>
        <motion.div variants={reveal} className="flex flex-wrap items-center gap-3">
          <StatusPill label="Live monitoring" />
          <span className="font-mono text-[0.72rem] tracking-[0.14em] text-muted uppercase">
            Updated {formatDate(overview.period_end, true)}
          </span>
        </motion.div>
        <motion.p variants={reveal} className="mt-8 font-mono text-xs tracking-[0.2em] text-signal uppercase">
          Match controversy report
        </motion.p>
        <motion.h1 variants={reveal} className="mt-4 max-w-3xl text-balance text-4xl font-semibold leading-[0.98] tracking-[-0.05em] sm:text-6xl lg:text-[4.6rem]">
          {overview.topic.name}
        </motion.h1>
        <motion.p variants={reveal} className="mt-7 max-w-2xl text-pretty text-base leading-7 text-muted sm:text-lg">
          {overview.summary}
        </motion.p>
        <motion.div variants={reveal} className="mt-8 flex flex-wrap gap-2">
          {overview.topic.keywords.map((keyword) => (
            <span key={keyword} className="rounded-full border border-line px-3 py-1.5 text-xs text-muted">
              {keyword}
            </span>
          ))}
        </motion.div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ delay: 0.24, duration: 0.8, ease }}
        className="relative overflow-hidden rounded-[2rem] border border-line bg-panel/90 p-6 shadow-2xl shadow-black/30 sm:p-8"
      >
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal/70 to-transparent" />
        <div className="flex items-start justify-between gap-5">
          <div>
            <p className="eyebrow">Current collected narrative</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">Leans against the decision</h2>
          </div>
          <ConfidenceDial value={overview.confidence_score} />
        </div>

        <div className="mt-10 flex items-end justify-between gap-5">
          <div>
            <AnimatedNumber value={against} suffix="%" className="text-5xl font-semibold tracking-[-0.06em] text-critical" />
            <p className="mt-2 text-xs text-muted">Critical / against</p>
          </div>
          <div className="text-right">
            <AnimatedNumber value={toward} suffix="%" className="text-5xl font-semibold tracking-[-0.06em] text-support" />
            <p className="mt-2 text-xs text-muted">Supportive / toward</p>
          </div>
        </div>
        <div className="relative mt-5 flex h-5 overflow-hidden rounded-full bg-white/5 p-1">
          <motion.div
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ delay: 0.55, duration: 1, ease }}
            style={{ width: `${against}%`, transformOrigin: "right" }}
            className="h-full rounded-l-full bg-critical"
          />
          <motion.div
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ delay: 0.55, duration: 1, ease }}
            style={{ width: `${toward}%`, transformOrigin: "left" }}
            className="h-full rounded-r-full bg-support"
          />
          <span className="absolute left-1/2 top-1/2 h-8 w-px -translate-x-1/2 -translate-y-1/2 bg-paper/70" />
        </div>
        <div className="mt-7 grid grid-cols-3 gap-2 border-t border-line pt-6">
          <MiniMetric label="Confidence" value={`${Math.round(overview.confidence_score * 100)}%`} />
          <MiniMetric label="Independent" value={overview.independent_content_groups.toString()} />
          <MiniMetric label="Syndicated" value={overview.syndicated_items.toString()} />
        </div>
      </motion.div>
    </section>
  );
}

function NarrativeSection({ metrics, channels }: { metrics: VisualizationMetric[]; channels: Record<string, number> }) {
  return (
    <RevealSection id="narratives" kicker="Discourse map" title="What the coverage is doing" description="Each stance is classified independently. Percentages describe the collected sample after syndicated coverage is controlled.">
      <div className="grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
        <Panel className="p-5 sm:p-7">
          <div className="space-y-6">
            {metrics.map((metric, index) => (
              <NarrativeBar key={metric.label} metric={metric} index={index} />
            ))}
          </div>
        </Panel>
        <Panel className="flex flex-col p-6 sm:p-7">
          <p className="eyebrow">Coverage composition</p>
          <div className="mt-7 flex flex-1 flex-col justify-center gap-5">
            {Object.entries(channels).map(([label, count], index) => {
              const total = Object.values(channels).reduce((sum, value) => sum + value, 0);
              const percent = Math.round((count / total) * 100);
              return (
                <div key={label}>
                  <div className="mb-2 flex items-center justify-between text-xs">
                    <span className="capitalize text-muted">{label}</span>
                    <span className="font-mono">{count}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                    <motion.div
                      initial={{ width: 0 }}
                      whileInView={{ width: `${percent}%` }}
                      viewport={{ once: true }}
                      transition={{ delay: index * 0.08, duration: 0.7, ease }}
                      className="h-full rounded-full bg-signal/70"
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="mt-7 border-t border-line pt-5 text-xs leading-5 text-muted">
            Channel balance is visible so a surge from one platform is not mistaken for broad consensus.
          </p>
        </Panel>
      </div>
    </RevealSection>
  );
}

function IncidentSection({ incidents, activeIncident, onSelect, currentIncident }: { incidents: IncidentView[]; activeIncident: string; onSelect: (id: string) => void; currentIncident: IncidentView }) {
  return (
    <RevealSection id="incidents" kicker="Incident intelligence" title="Where the controversy concentrates" description="Related descriptions are clustered into incidents while preserving independent-source and syndication counts.">
      <div className="grid gap-5 lg:grid-cols-[0.78fr_1.22fr]">
        <div className="space-y-3" role="tablist" aria-label="Controversial incidents">
          {incidents.map((incident, index) => {
            const selected = incident.incident_id === activeIncident;
            return (
              <motion.button
                layout
                key={incident.incident_id}
                type="button"
                role="tab"
                aria-controls="incident-detail"
                aria-selected={selected}
                onClick={() => onSelect(incident.incident_id)}
                whileHover={{ x: 4 }}
                className={`relative w-full overflow-hidden rounded-2xl border p-5 text-left transition ${selected ? "border-signal/45 bg-signal/[0.07]" : "border-line bg-panel/60 hover:border-white/20"}`}
              >
                {selected && <motion.span layoutId="incident-active" className="absolute inset-y-4 left-0 w-0.5 rounded-full bg-signal" />}
                <div className="flex items-start justify-between gap-5">
                  <div>
                    <p className="font-mono text-[0.72rem] tracking-[0.14em] text-muted uppercase">Incident 0{index + 1}</p>
                    <p className="mt-2 font-medium">{formatLabel(incident.controversy_type)}</p>
                  </div>
                  <span className="rounded-full border border-line px-2.5 py-1 font-mono text-xs text-muted">
                    {incident.match_minute === null ? "Context" : `${incident.match_minute}′`}
                  </span>
                </div>
                <p className="mt-4 text-xs text-muted">{incident.independent_content_groups} independent groups</p>
              </motion.button>
            );
          })}
        </div>
        <motion.article
          id="incident-detail"
          key={currentIncident.incident_id}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative overflow-hidden rounded-[2rem] border border-line bg-panel p-6 sm:p-8"
          role="tabpanel"
        >
          <div className="absolute right-[-3rem] top-[-4rem] size-44 rounded-full border border-signal/10" />
          <div className="absolute right-3 top-0 h-32 w-32 bg-signal/5 blur-3xl" />
          <p className="eyebrow">{formatLabel(currentIncident.controversy_type)}</p>
          <h3 className="mt-5 max-w-2xl text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
            {currentIncident.description}
          </h3>
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            <Decision label="On-field decision" value={currentIncident.on_field_decision ?? "Not applicable"} />
            <Decision label="Review outcome" value={currentIncident.review_outcome ?? "No review recorded"} />
          </div>
          <div className="mt-8 flex flex-wrap gap-6 border-t border-line pt-6">
            <DataPoint value={currentIncident.item_count} label="mentions" />
            <DataPoint value={currentIncident.source_count} label="sources" />
            <DataPoint value={currentIncident.independent_content_groups} label="independent" />
            <DataPoint value={currentIncident.syndicated_items} label="syndicated" />
          </div>
          {currentIncident.consensus.length > 0 ? (
            <div className="mt-7 rounded-2xl border border-support/20 bg-support/[0.05] p-5">
              <p className="text-xs font-semibold text-support">Qualified-source signal</p>
              <p className="mt-2 text-sm leading-6 text-muted">{currentIncident.consensus[0].summary}</p>
            </div>
          ) : (
            <div className="mt-7 rounded-2xl border border-line bg-white/[0.025] p-5 text-sm text-muted">
              No qualified-source consensus threshold has been met for this incident.
            </div>
          )}
        </motion.article>
      </div>
    </RevealSection>
  );
}

function TimelineSection({ points }: { points: TimelinePoint[] }) {
  const path = points.map((point, index) => {
    const x = 42 + index * (516 / Math.max(points.length - 1, 1));
    const y = 180 - ((point.against_percent ?? 50) / 100) * 130;
    return `${index === 0 ? "M" : "L"}${x},${y}`;
  }).join(" ");

  return (
    <RevealSection id="timeline" kicker="Narrative velocity" title="How the story moved" description="The trend tracks report snapshots, not individual viral posts, so movement reflects changes across independently collected coverage.">
      <Panel className="overflow-hidden p-5 sm:p-8">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div className="flex gap-5 text-xs text-muted">
            <span className="flex items-center gap-2"><i className="size-2 rounded-full bg-critical" /> Against decision</span>
            <span className="flex items-center gap-2"><i className="size-2 rounded-full bg-support" /> Toward decision</span>
          </div>
          <span className="rounded-full border border-line px-3 py-1.5 font-mono text-[0.72rem] text-muted">8-day window</span>
        </div>
        <div className="overflow-x-auto">
          <svg viewBox="0 0 600 220" className="min-w-[600px]" role="img" aria-label="Narrative trend moved from 48 to 60 percent against the decision">
            {[50, 100, 150].map((y) => <line key={y} x1="40" y1={y} x2="560" y2={y} stroke="rgba(226,236,228,.09)" strokeDasharray="4 8" />)}
            <motion.path d={path} fill="none" stroke="var(--critical)" strokeWidth="3" strokeLinecap="round" initial={{ pathLength: 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: 1.3, ease }} />
            {points.map((point, index) => {
              const x = 42 + index * (516 / Math.max(points.length - 1, 1));
              const y = 180 - ((point.against_percent ?? 50) / 100) * 130;
              return (
                <g key={point.report_id}>
                  <motion.circle cx={x} cy={y} r="6" fill="var(--ink)" stroke="var(--critical)" strokeWidth="3" initial={{ scale: 0 }} whileInView={{ scale: 1 }} viewport={{ once: true }} transition={{ delay: 0.45 + index * 0.15, type: "spring" }} />
                  <text x={x} y="205" textAnchor="middle" fill="var(--muted)" fontSize="11">{formatDate(point.timestamp)}</text>
                  <text x={x} y={y - 15} textAnchor="middle" fill="var(--paper)" fontSize="12" fontWeight="600">{point.against_percent}%</text>
                </g>
              );
            })}
          </svg>
        </div>
      </Panel>
    </RevealSection>
  );
}

function ConsensusSection({ consensus }: { consensus?: ConsensusResult }) {
  if (!consensus) return null;
  const percent = consensus.leading_percent ?? 0;
  return (
    <RevealSection id="consensus" kicker="Qualified-source consensus" title="What officiating experts said" description="Repeated publication of one person’s view counts once. Credentials, direct sourcing, and independence affect source quality.">
      <div className="grid gap-5 lg:grid-cols-[0.84fr_1.16fr]">
        <Panel className="grid place-items-center p-8 text-center">
          <div className="relative grid size-56 place-items-center">
            <svg viewBox="0 0 180 180" className="absolute inset-0 -rotate-90" aria-hidden>
              <circle cx="90" cy="90" r="74" fill="none" stroke="rgba(226,236,228,.08)" strokeWidth="10" />
              <motion.circle cx="90" cy="90" r="74" fill="none" stroke="var(--signal)" strokeWidth="10" strokeLinecap="round" pathLength="100" strokeDasharray="100" initial={{ strokeDashoffset: 100 }} whileInView={{ strokeDashoffset: 100 - percent }} viewport={{ once: true }} transition={{ duration: 1.1, ease }} />
            </svg>
            <div>
              <AnimatedNumber value={percent} suffix="%" className="text-5xl font-semibold tracking-[-0.06em]" />
              <p className="mt-2 text-xs text-muted">disagreed with decision</p>
            </div>
          </div>
          <span className="mt-4 rounded-full border border-signal/25 bg-signal/[0.07] px-3 py-1.5 text-xs font-medium text-signal">
            {formatLabel(consensus.status)}
          </span>
        </Panel>
        <Panel className="p-6 sm:p-8">
          <p className="eyebrow">Collected expert judgment</p>
          <blockquote className="mt-5 text-2xl font-medium leading-snug tracking-tight sm:text-3xl">
            “{consensus.summary}”
          </blockquote>
          <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MiniMetric label="Independent" value={consensus.independent_opinions.toString()} />
            <MiniMetric label="Extracted" value={consensus.extracted_opinions.toString()} />
            <MiniMetric label="Duplicates" value={consensus.duplicate_mentions.toString()} />
            <MiniMetric label="Source quality" value={`${Math.round(consensus.average_source_quality * 100)}%`} />
          </div>
          <div className="mt-7 border-t border-line pt-5">
            {consensus.limitations.map((limitation) => (
              <p key={limitation} className="mt-2 flex gap-3 text-xs leading-5 text-muted">
                <span className="text-signal" aria-hidden>•</span>{limitation}
              </p>
            ))}
          </div>
        </Panel>
      </div>
    </RevealSection>
  );
}

function FindingsSection({ fixture }: { fixture: FootballReportFixture }) {
  const { overview, incidents } = fixture;
  return (
    <RevealSection id="findings" kicker="Evidence boundary" title="What can be stated responsibly" description="Findings are limited to stored evidence and observable properties of the collected sample.">
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel className="p-6 sm:p-8">
          <p className="eyebrow">Supported findings</p>
          <ol className="mt-7 space-y-5">
            {overview.verified_findings.map((finding, index) => (
              <li key={finding} className="flex gap-4">
                <span className="grid size-7 shrink-0 place-items-center rounded-full border border-signal/30 bg-signal/[0.06] font-mono text-[0.72rem] text-signal">0{index + 1}</span>
                <p className="text-sm leading-6 text-paper/85">{finding}</p>
              </li>
            ))}
          </ol>
        </Panel>
        <Panel className="p-6 sm:p-8">
          <p className="eyebrow">Methodology & limits</p>
          <p className="mt-6 text-sm leading-7 text-muted">{overview.methodology}</p>
          <div className="mt-6 border-t border-line pt-4">
            {[...overview.limitations, ...incidents.limitations].slice(0, 4).map((limitation) => (
              <p key={limitation} className="mt-3 flex gap-3 text-xs leading-5 text-muted">
                <span aria-hidden className="text-critical">—</span>{limitation}
              </p>
            ))}
          </div>
        </Panel>
      </div>
      <div className="mt-5 rounded-2xl border border-critical/20 bg-critical/[0.04] px-5 py-4 text-xs leading-5 text-muted">
        BiasRadar describes patterns in published material. It does not infer hidden intent or treat narrative prevalence as proof that an allegation is true.
      </div>
    </RevealSection>
  );
}

function RevealSection({ id, kicker, title, description, children }: { id: string; kicker: string; title: string; description: string; children: React.ReactNode }) {
  return (
    <motion.section id={id} initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-90px" }} variants={{ visible: { transition: { staggerChildren: 0.08 } } }} className="scroll-mt-24 pt-28">
      <motion.p variants={reveal} className="eyebrow">{kicker}</motion.p>
      <motion.div variants={reveal} className="mb-9 mt-3 grid gap-4 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
        <h2 className="text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">{title}</h2>
        <p className="max-w-2xl text-sm leading-6 text-muted lg:justify-self-end">{description}</p>
      </motion.div>
      <motion.div variants={reveal}>{children}</motion.div>
    </motion.section>
  );
}

function NarrativeBar({ metric, index }: { metric: VisualizationMetric; index: number }) {
  return (
    <div>
      <div className="mb-2.5 flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium">{formatLabel(metric.label)}</p>
          <p className="mt-1 text-[0.72rem] leading-5 text-muted">{metric.item_count} classified items · {Math.round(metric.confidence * 100)}% confidence</p>
        </div>
        <div className="flex items-center gap-2">
          {metric.trend !== null && <span className={`font-mono text-[0.72rem] ${metric.trend > 0 ? "text-critical" : "text-support"}`}>{metric.trend > 0 ? "+" : ""}{metric.trend} pts</span>}
          <span className="font-mono text-sm font-semibold">{metric.percentage}%</span>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/5">
        <motion.div initial={{ width: 0 }} whileInView={{ width: `${metric.percentage}%` }} viewport={{ once: true }} transition={{ delay: 0.1 + index * 0.08, duration: 0.75, ease }} className={`h-full rounded-full ${index === 0 ? "bg-critical" : index === 3 ? "bg-support" : "bg-signal/65"}`} />
      </div>
    </div>
  );
}

function StatCard({ value, label, note, delay }: { value: number; label: string; note: string; delay: number }) {
  return (
    <motion.article initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay }} className="rounded-2xl border border-line bg-panel/60 p-5 backdrop-blur">
      <AnimatedNumber value={value} className="text-3xl font-semibold tracking-[-0.04em]" />
      <p className="mt-3 text-sm font-medium">{label}</p>
      <p className="mt-1 text-xs text-muted">{note}</p>
    </motion.article>
  );
}

function AnimatedNumber({ value, suffix = "", className = "" }: { value: number; suffix?: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const motionValue = useMotionValue(0);
  const rounded = useTransform(motionValue, (latest) => `${Math.round(latest)}${suffix}`);
  useEffect(() => {
    if (!inView) return;
    const controls = animate(motionValue, value, { duration: 0.9, ease });
    return () => controls.stop();
  }, [inView, motionValue, value]);
  return <motion.span ref={ref} className={className}>{rounded}</motion.span>;
}

function ConfidenceDial({ value }: { value: number }) {
  return (
    <div className="relative grid size-16 shrink-0 place-items-center rounded-full border border-line bg-ink/50">
      <svg viewBox="0 0 64 64" className="absolute inset-0 -rotate-90" aria-hidden>
        <motion.circle cx="32" cy="32" r="29" fill="none" stroke="var(--signal)" strokeWidth="2" pathLength="1" initial={{ pathLength: 0 }} animate={{ pathLength: value }} transition={{ delay: 0.8, duration: 0.9, ease }} />
      </svg>
      <span className="font-mono text-[0.72rem]">{Math.round(value * 100)}%</span>
    </div>
  );
}

function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-[1.65rem] border border-line bg-panel/75 ${className}`}>{children}</div>;
}

function StatusPill({ label }: { label: string }) {
  return <span className="flex items-center gap-2 rounded-full border border-signal/25 bg-signal/[0.06] px-3 py-1.5 text-xs text-signal"><i className="relative flex size-1.5"><i className="absolute size-full animate-ping rounded-full bg-signal opacity-50" /><i className="relative size-1.5 rounded-full bg-signal" /></i>{label}</span>;
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <div><p className="text-lg font-semibold">{value}</p><p className="mt-1 text-[0.72rem] text-muted">{label}</p></div>;
}

function DataPoint({ value, label }: { value: number; label: string }) {
  return <div><p className="font-mono text-lg font-semibold">{value}</p><p className="mt-1 text-[0.72rem] text-muted">{label}</p></div>;
}

function Decision({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-line bg-white/[0.025] p-4"><p className="font-mono text-[0.7rem] tracking-[0.12em] text-muted uppercase">{label}</p><p className="mt-2 text-sm leading-6">{value}</p></div>;
}

function LowConfidenceState() {
  return <div className="mt-10 rounded-2xl border border-amber-300/25 bg-amber-300/[0.06] p-5 text-sm text-amber-100">This report has low confidence. Treat the percentages as preliminary until broader independent coverage is available.</div>;
}

function formatLabel(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string, includeTime = false) {
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}) }).format(new Date(value));
}
