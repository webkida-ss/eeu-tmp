import Link from "next/link";
import { notFound } from "next/navigation";
import { getLearningPathRepository } from "@/features/learning/repositories/learningPathRepository";

export default async function LearningPathDetailPage({
  params,
}: {
  params: Promise<{ pathId: string }>;
}) {
  const { pathId } = await params;
  const learningPathRepository = getLearningPathRepository();
  const learningPath = await learningPathRepository.getLearningPath(pathId);

  if (!learningPath) {
    notFound();
  }

  return (
    <main className="min-h-screen bg-amber-50 px-6 py-10 text-amber-950">
      <div className="mx-auto max-w-6xl">
        <Link
          href="/learning-paths"
          className="text-sm font-semibold text-amber-700 transition-colors hover:text-amber-500"
        >
          Back to learning paths
        </Link>

        <section className="mt-12 grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
          <div>
            <p className="text-sm font-bold uppercase tracking-[0.28em] text-amber-600">
              Learning path
            </p>
            <h1 className="mt-4 text-5xl font-extrabold tracking-tight">
              {learningPath.title}
            </h1>
            <p className="mt-5 text-xl leading-8 text-amber-800">
              {learningPath.description}
            </p>
          </div>
          <div className="rounded-3xl border border-amber-200 bg-white p-7 shadow-sm">
            <p className="text-sm font-bold uppercase tracking-[0.22em] text-amber-500">
              Best for
            </p>
            <p className="mt-3 text-base leading-7 text-amber-800">
              {learningPath.audience}
            </p>
          </div>
        </section>

        <section className="mt-12">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="text-sm font-bold uppercase tracking-[0.24em] text-amber-600">
                Courses
              </p>
              <h2 className="mt-2 text-3xl font-extrabold">
                Pick your current target.
              </h2>
            </div>
            <p className="text-sm font-semibold text-amber-700">
              {learningPath.courses.length} available courses
            </p>
          </div>

          <div className="mt-6 grid gap-5 lg:grid-cols-3">
            {learningPath.courses.map((course) => (
              <Link
                key={course.id}
                href={`/learning-paths/${learningPath.id}/courses/${course.id}`}
                className="group rounded-3xl border border-amber-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
              >
                <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-500">
                  {course.levelLabel}
                </p>
                <h3 className="mt-4 text-2xl font-extrabold">{course.title}</h3>
                <div className="mt-6 flex items-center justify-between border-t border-amber-100 pt-5 text-sm font-bold text-amber-700">
                  <span>{course.units.length} units</span>
                  <span>{course.estimatedHours} hours</span>
                </div>
                <p className="mt-5 text-sm font-bold text-amber-700 transition group-hover:text-amber-500">
                  Open course
                </p>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
