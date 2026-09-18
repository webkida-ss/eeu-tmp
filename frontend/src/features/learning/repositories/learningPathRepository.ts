import jsonLearningPaths from "@/features/learning/data/learningPaths.json";
import { mockLearningPaths } from "@/features/learning/data/learningPaths";
import type { Course, LearningPath } from "@/features/learning/types/learning";
import {
  getLearningPath as fetchLearningPath,
  getLearningPathCourse as fetchLearningPathCourse,
  getLearningPaths as fetchLearningPaths,
} from "@/lib/api/generated/sdk.gen";
import { selectRepository } from "@/lib/repositorySelector";

export type LearningPathRepository = {
  getLearningPaths: () => Promise<LearningPath[]>;
  getLearningPath: (pathId: string) => Promise<LearningPath | undefined>;
  getCourse: (pathId: string, courseId: string) => Promise<Course | undefined>;
};

function createStaticLearningPathRepository(
  paths: LearningPath[],
): LearningPathRepository {
  return {
    async getLearningPaths() {
      return paths;
    },
    async getLearningPath(pathId: string) {
      return paths.find((path) => path.id === pathId);
    },
    async getCourse(pathId: string, courseId: string) {
      const learningPath = paths.find((path) => path.id === pathId);

      return learningPath?.courses.find((course) => course.id === courseId);
    },
  };
}

function requireApiData<T>(data: T | undefined, message: string): T {
  if (data === undefined) {
    throw new Error(message);
  }

  return data;
}

function createApiLearningPathRepository(): LearningPathRepository {
  const baseUrl =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:18080";

  return {
    async getLearningPaths() {
      const response = await fetchLearningPaths({ baseUrl });

      if (response.error) {
        throw new Error("Failed to fetch learning paths.");
      }

      return requireApiData(response.data, "Failed to fetch learning paths.");
    },
    async getLearningPath(pathId: string) {
      const response = await fetchLearningPath({
        baseUrl,
        path: { pathId },
      });

      if (response.response?.status === 404) {
        return undefined;
      }

      if (response.error) {
        throw new Error("Failed to fetch a learning path.");
      }

      return requireApiData(response.data, "Failed to fetch a learning path.");
    },
    async getCourse(pathId: string, courseId: string) {
      const response = await fetchLearningPathCourse({
        baseUrl,
        path: { pathId, courseId },
      });

      if (response.response?.status === 404) {
        return undefined;
      }

      if (response.error) {
        throw new Error("Failed to fetch a course.");
      }

      return requireApiData(response.data, "Failed to fetch a course.");
    },
  };
}

export function getLearningPathRepository(): LearningPathRepository {
  const jsonRepository = createStaticLearningPathRepository(
    jsonLearningPaths as LearningPath[],
  );
  const mockRepository = createStaticLearningPathRepository(mockLearningPaths);
  const apiRepository = createApiLearningPathRepository();

  return selectRepository({
    json: jsonRepository,
    mock: mockRepository,
    api: apiRepository,
  });
}
