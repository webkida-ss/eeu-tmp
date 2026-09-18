import type { ExampleSentence } from "@/features/learning/types/learning";
import { generateExampleSentence } from "@/lib/api/generated/sdk.gen";
import { selectRepository } from "@/lib/repositorySelector";

export type GeneratePersonalizedExampleSentenceInput = {
  targetText: string;
  userContextSummary: string;
  accessToken?: string;
};

export type ExampleSentenceRepository = {
  generatePersonalizedExampleSentence: (
    input: GeneratePersonalizedExampleSentenceInput,
  ) => Promise<ExampleSentence>;
};

function createStaticExampleSentenceRepository(): ExampleSentenceRepository {
  return {
    async generatePersonalizedExampleSentence(input) {
      return {
        id: `local-${input.targetText}`,
        targetText: input.targetText,
        targetSentence: `I use "${input.targetText}" in a sentence that matches my learning context.`,
        sourceTranslation: "",
        variant: "personalized",
        personalization: {
          contextSummary: input.userContextSummary,
        },
      };
    },
  };
}

function createApiExampleSentenceRepository(): ExampleSentenceRepository {
  const baseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    process.env.API_BASE_URL ??
    "http://localhost:18080";

  return {
    async generatePersonalizedExampleSentence(input) {
      if (!input.accessToken) {
        throw new Error("Authentication is required to generate example sentences.");
      }

      const response = await generateExampleSentence({
        baseUrl,
        auth: input.accessToken,
        body: {
          targetText: input.targetText,
          userContextSummary: input.userContextSummary,
        },
      });

      if (response.error) {
        throw new Error("Failed to generate an example sentence.");
      }

      if (!response.data) {
        throw new Error("Generated example sentence response was empty.");
      }

      return response.data;
    },
  };
}

export function getExampleSentenceRepository(): ExampleSentenceRepository {
  const staticRepository = createStaticExampleSentenceRepository();
  const apiRepository = createApiExampleSentenceRepository();

  return selectRepository({
    json: staticRepository,
    mock: staticRepository,
    api: apiRepository,
  });
}
