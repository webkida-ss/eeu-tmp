import {
  getLearnerProfile,
  putLearnerProfile,
} from "@/lib/api/generated/sdk.gen";
import type { LearnerProfile } from "@/lib/api/generated/types.gen";
import { selectRepository } from "@/lib/repositorySelector";

export type LearnerProfileDraft = Omit<LearnerProfile, "updatedAt">;

export type LearnerProfileRepository = {
  getLearnerProfile: (accessToken?: string) => Promise<LearnerProfileDraft>;
  saveLearnerProfile: (
    profile: LearnerProfileDraft,
    accessToken?: string,
  ) => Promise<LearnerProfileDraft>;
};

const emptyLearnerProfile: LearnerProfileDraft = {
  learningPurpose: "",
  targetLevel: "",
  deadline: "",
  interests: "",
  favoriteContent: "",
  dailyScenes: "",
  englishUseCases: "",
  weakPoints: "",
  vocabularyFocus: "",
};

function createStaticLearnerProfileRepository(): LearnerProfileRepository {
  let profile = { ...emptyLearnerProfile };

  return {
    async getLearnerProfile() {
      return profile;
    },
    async saveLearnerProfile(input) {
      profile = { ...input };

      return profile;
    },
  };
}

function createApiLearnerProfileRepository(): LearnerProfileRepository {
  const baseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    process.env.API_BASE_URL ??
    "http://localhost:18080";

  return {
    async getLearnerProfile(accessToken) {
      if (!accessToken) {
        throw new Error("Authentication is required to load learner profile.");
      }

      const response = await getLearnerProfile({
        baseUrl,
        auth: accessToken,
      });

      if (response.error || !response.data) {
        throw new Error("Failed to load learner profile.");
      }

      return response.data;
    },
    async saveLearnerProfile(profile, accessToken) {
      if (!accessToken) {
        throw new Error("Authentication is required to save learner profile.");
      }

      const response = await putLearnerProfile({
        baseUrl,
        auth: accessToken,
        body: profile,
      });

      if (response.error || !response.data) {
        throw new Error("Failed to save learner profile.");
      }

      return response.data;
    },
  };
}

export function getLearnerProfileRepository(): LearnerProfileRepository {
  const staticRepository = createStaticLearnerProfileRepository();
  const apiRepository = createApiLearnerProfileRepository();

  return selectRepository({
    json: staticRepository,
    mock: staticRepository,
    api: apiRepository,
  });
}
