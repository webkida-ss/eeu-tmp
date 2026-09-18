import Link from "next/link";
import { getLearningPathRepository } from "@/features/learning/repositories/learningPathRepository";

export default async function LearningPathsPage() {
  const learningPathRepository = getLearningPathRepository();
  const learningPaths = await learningPathRepository.getLearningPaths();

  return (
    <main className="min-h-screen bg-amber-50 px-6 py-10 text-amber-950">
      <div className="mx-auto max-w-5xl">
        <Link
          href="/"
          className="text-sm font-semibold text-amber-700 transition-colors hover:text-amber-500"
        >
          Back to home
        </Link>

        <section className="mt-12 max-w-3xl">
          <p className="text-sm font-bold uppercase tracking-[0.28em] text-amber-600">
            Learning paths
          </p>
          <h1 className="mt-4 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Choose a path, then learn through focused units.
          </h1>
          <p className="mt-5 text-lg leading-8 text-amber-800">
            Each path gives you a clear entry point. Courses break that path into
            levels, and units bundle target vocabulary with practical examples.
          </p>
        </section>

        <section className="mt-12 grid gap-6 md:grid-cols-2">
          {learningPaths.map((path) => (
            <Link
              key={path.id}
              href={`/learning-paths/${path.id}`}
              className="group rounded-3xl border border-amber-200 bg-white p-7 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
            >
              <p className="text-sm font-bold uppercase tracking-[0.24em] text-amber-500">
                {path.courses.length} courses
              </p>
              <h2 className="mt-4 text-3xl font-extrabold">{path.title}</h2>
              <p className="mt-3 text-base leading-7 text-amber-800">
                {path.tagline}
              </p>
              <p className="mt-6 text-sm font-bold text-amber-700 transition group-hover:text-amber-500">
                View path
              </p>
            </Link>
          ))}
        </section>
      </div>
    </main>
  );
}
