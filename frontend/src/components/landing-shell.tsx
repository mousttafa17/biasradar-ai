"use client";

import { motion, MotionConfig } from "motion/react";
import Link from "next/link";

const rise = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0 },
};

export function LandingShell() {
  return (
    <MotionConfig reducedMotion="user">
      <main className="relative min-h-screen overflow-hidden bg-ink text-paper">
      <div className="pitch-grid pointer-events-none absolute inset-0 opacity-30" />
      <div className="glow pointer-events-none absolute left-1/2 top-[-24rem] h-[42rem] w-[42rem] -translate-x-1/2 rounded-full" />

      <nav className="relative z-10 mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-7 lg:px-10">
        <a className="flex items-center gap-3" href="#top" aria-label="BiasRadar home">
          <span className="grid size-9 place-items-center rounded-full border border-signal/40 bg-signal/10 text-sm font-semibold text-signal">
            BR
          </span>
          <span className="text-sm font-semibold tracking-[0.18em] uppercase">
            BiasRadar <span className="text-muted">Football</span>
          </span>
        </a>
        <span className="rounded-full border border-line bg-panel/70 px-3 py-1.5 font-mono text-[0.72rem] tracking-[0.16em] text-muted uppercase backdrop-blur">
          Intelligence preview
        </span>
      </nav>

      <section
        id="top"
        className="relative z-10 mx-auto grid min-h-[calc(100vh-96px)] w-full max-w-7xl items-center gap-14 px-6 pb-20 pt-10 lg:grid-cols-[1.08fr_0.92fr] lg:px-10"
      >
        <motion.div
          initial="hidden"
          animate="visible"
          transition={{ staggerChildren: 0.09 }}
        >
          <motion.p
            variants={rise}
            className="mb-6 flex items-center gap-3 font-mono text-xs tracking-[0.2em] text-signal uppercase"
          >
            <span className="h-px w-8 bg-signal" />
            Football narrative intelligence
          </motion.p>
          <motion.h1
            variants={rise}
            className="max-w-3xl text-balance text-5xl font-semibold leading-[0.96] tracking-[-0.055em] sm:text-7xl lg:text-[5.25rem]"
          >
            See where the football story is really leaning.
          </motion.h1>
          <motion.p
            variants={rise}
            className="mt-7 max-w-xl text-pretty text-base leading-7 text-muted sm:text-lg"
          >
            BiasRadar maps coverage, claims, incidents, and attributed expert
            judgments into one evidence-aware view of a controversy.
          </motion.p>
          <motion.form
            variants={rise}
            className="mt-10 flex max-w-2xl flex-col gap-3 rounded-2xl border border-line bg-panel/80 p-2 shadow-2xl shadow-black/30 backdrop-blur sm:flex-row"
          >
            <label className="sr-only" htmlFor="controversy">
              Football controversy
            </label>
            <input
              id="controversy"
              className="min-h-12 min-w-0 flex-1 bg-transparent px-4 text-sm text-paper outline-none placeholder:text-muted/60"
              placeholder="e.g. Argentina FIFA favoritism"
              type="search"
            />
            <Link
              className="inline-flex min-h-12 items-center justify-center rounded-xl bg-signal px-6 text-sm font-semibold text-ink transition hover:bg-signal-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal"
              href="/topics/demo"
            >
              Analyze controversy
            </Link>
          </motion.form>
          <motion.p variants={rise} className="mt-4 text-xs text-muted/70">
            Analysis describes collected discourse—not hidden intent or proof of
            corruption.
          </motion.p>
        </motion.div>

        <NarrativePreview />
      </section>
      </main>
    </MotionConfig>
  );
}

function NarrativePreview() {
  return (
    <motion.aside
      initial={{ opacity: 0, scale: 0.97, y: 24 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ delay: 0.32, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
      className="relative rounded-3xl border border-line bg-panel/85 p-5 shadow-2xl shadow-black/40 backdrop-blur-xl sm:p-7"
      aria-label="Example narrative analysis"
    >
      <div className="flex items-start justify-between gap-6 border-b border-line pb-5">
        <div>
          <p className="font-mono text-[0.72rem] tracking-[0.16em] text-muted uppercase">
            Current narrative
          </p>
          <h2 className="mt-2 text-xl font-semibold">Officiating controversy</h2>
        </div>
        <span className="flex items-center gap-2 text-xs text-muted">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-signal opacity-50" />
            <span className="relative inline-flex size-2 rounded-full bg-signal" />
          </span>
          Monitoring
        </span>
      </div>

      <div className="py-7">
        <div className="mb-3 flex items-end justify-between gap-8">
          <div>
            <strong className="text-4xl tracking-[-0.05em] text-critical">60%</strong>
            <p className="mt-1 text-xs text-muted">Criticizes referee</p>
          </div>
          <div className="text-right">
            <strong className="text-4xl tracking-[-0.05em] text-support">40%</strong>
            <p className="mt-1 text-xs text-muted">Defends referee</p>
          </div>
        </div>
        <div className="relative flex h-3 overflow-hidden rounded-full bg-white/5">
          <motion.span
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ delay: 0.7, duration: 0.85, ease: [0.22, 1, 0.36, 1] }}
            style={{ transformOrigin: "right" }}
            className="block w-3/5 bg-critical"
          />
          <motion.span
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ delay: 0.7, duration: 0.85, ease: [0.22, 1, 0.36, 1] }}
            style={{ transformOrigin: "left" }}
            className="block w-2/5 bg-support"
          />
          <span className="absolute left-3/5 top-1/2 h-6 w-px -translate-y-1/2 bg-paper" />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          ["18", "Sources"],
          ["14", "Independent"],
          ["72%", "Confidence"],
        ].map(([value, label]) => (
          <div key={label} className="rounded-xl border border-line bg-white/[0.025] p-3">
            <p className="text-lg font-semibold">{value}</p>
            <p className="mt-1 truncate text-[0.72rem] text-muted">{label}</p>
          </div>
        ))}
      </div>

      <p className="mt-5 border-l border-signal/60 pl-3 text-xs leading-5 text-muted">
        Example interface using illustrative data. Live results will include
        evidence, methodology, and limitations.
      </p>
    </motion.aside>
  );
}
