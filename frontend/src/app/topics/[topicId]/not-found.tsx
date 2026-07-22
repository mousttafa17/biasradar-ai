import Link from "next/link";

export default function TopicNotFound() {
  return (
    <main className="grid min-h-screen place-items-center bg-ink px-6 text-paper">
      <div className="max-w-lg text-center">
        <p className="font-mono text-xs tracking-[0.18em] text-signal uppercase">
          No report found
        </p>
        <h1 className="mt-4 text-4xl font-semibold tracking-tight">
          This controversy has not been analyzed yet.
        </h1>
        <Link
          href="/"
          className="mt-8 inline-flex rounded-full border border-line px-6 py-3 text-sm"
        >
          Start a new analysis
        </Link>
      </div>
    </main>
  );
}
