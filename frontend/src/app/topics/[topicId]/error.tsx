"use client";

export default function TopicReportError({
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-ink px-6 text-paper">
      <div className="max-w-lg rounded-3xl border border-line bg-panel p-8 text-center">
        <p className="font-mono text-xs tracking-[0.18em] text-critical uppercase">
          Report unavailable
        </p>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight">
          The analysis could not be loaded.
        </h1>
        <p className="mt-4 leading-7 text-muted">
          Your report data is safe. Retry the request or return to the topic search.
        </p>
        <button
          onClick={() => unstable_retry()}
          className="mt-7 rounded-full bg-signal px-6 py-3 text-sm font-semibold text-ink"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
