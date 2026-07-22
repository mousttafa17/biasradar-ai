export default function LoadingTopicReport() {
  return (
    <main className="min-h-screen bg-ink px-6 py-8 text-paper" aria-busy="true">
      <div className="mx-auto max-w-7xl">
        <div className="skeleton h-10 w-52 rounded-full" />
        <div className="mt-20 grid gap-10 lg:grid-cols-[1fr_0.8fr]">
          <div>
            <div className="skeleton h-4 w-36 rounded" />
            <div className="skeleton mt-6 h-20 max-w-2xl rounded-2xl" />
            <div className="skeleton mt-5 h-5 max-w-lg rounded" />
          </div>
          <div className="skeleton h-80 rounded-3xl" />
        </div>
        <span className="sr-only">Loading controversy report</span>
      </div>
    </main>
  );
}
