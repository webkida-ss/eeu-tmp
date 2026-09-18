import Link from "next/link";
import { notFound } from "next/navigation";
import { getLearningPathRepository } from "@/features/learning/repositories/learningPathRepository";
import { CourseDetailTabs } from "@/features/learning/components/CourseDetailTabs";

export default async function CourseDetailPage({
  params,
}: {
  params: Promise<{ pathId: string; courseId: string }>;
}) {
  const { pathId, courseId } = await params;
  const learningPathRepository = getLearningPathRepository();
  const [learningPath, course] = await Promise.all([
    learningPathRepository.getLearningPath(pathId),
    learningPathRepository.getCourse(pathId, courseId),
  ]);

  if (!learningPath || !course) {
    notFound();
  }

  return (
    <main className="min-h-screen bg-amber-50 px-6 py-10 text-amber-950">
      <div className="mx-auto max-w-6xl">
        <Link
          href={`/learning-paths/${learningPath.id}`}
          className="text-sm font-semibold text-amber-700 transition-colors hover:text-amber-500"
        >
          Back to {learningPath.title}
        </Link>

        <section className="mt-12 rounded-[2rem] border border-amber-200 bg-white p-8 shadow-sm sm:p-10">
          <p className="text-sm font-bold uppercase tracking-[0.28em] text-amber-600">
            {learningPath.title} course
          </p>
          <h1 className="mt-5 text-4xl font-extrabold tracking-tight sm:text-5xl">
            {course.title}
          </h1>
          <p className="mt-5 max-w-3xl text-lg leading-8 text-amber-800">
            {course.description}
          </p>
        </section>

        <CourseDetailTabs course={course} />
      </div>
    </main>
  );
}
