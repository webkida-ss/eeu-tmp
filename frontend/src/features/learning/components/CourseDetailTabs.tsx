"use client";

import { useMemo, useState } from "react";
import { getCurrentOidcUser } from "@/features/auth/lib/oidcClient";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { getExampleSentenceRepository } from "@/features/learning/repositories/exampleSentenceRepository";
import type {
  Course,
  ExampleSentence,
  VocabularyEntry,
} from "@/features/learning/types/learning";

type CourseDetailTabsProps = {
  course: Course;
};

type PracticeResult = "known" | "unknown";
type ProgressStatus = "notStarted" | "learning" | "remembered";
type ContentTab = "vocabulary" | "examples";

export function CourseDetailTabs({ course }: CourseDetailTabsProps) {
  const auth = useAuth();
  const [activeContentTab, setActiveContentTab] =
    useState<ContentTab>("vocabulary");
  const [practiceEntries, setPracticeEntries] = useState<VocabularyEntry[]>([]);
  const [practiceIndex, setPracticeIndex] = useState(0);
  const [isExplanationVisible, setIsExplanationVisible] = useState(false);
  const [practiceResults, setPracticeResults] = useState<
    Record<string, PracticeResult>
  >({});
  const [syncedProgressStatuses, setSyncedProgressStatuses] = useState<
    Record<string, ProgressStatus>
  >({});
  const [generatedExampleSentences, setGeneratedExampleSentences] = useState<
    Record<string, ExampleSentence[]>
  >({});
  const [generatingEntryId, setGeneratingEntryId] = useState<string | null>(null);
  const [generationErrors, setGenerationErrors] = useState<Record<string, string>>(
    {},
  );
  const exampleSentenceRepository = useMemo(
    () => getExampleSentenceRepository(),
    [],
  );
  const vocabularyEntries = useMemo(
    () => course.units.flatMap((unit) => unit.vocabularyEntries),
    [course.units],
  );
  const activePracticeEntry = practiceEntries[practiceIndex];
  const isPracticeSummaryVisible =
    practiceEntries.length > 0 && practiceIndex >= practiceEntries.length;

  function openVocabularyPractice(entry: VocabularyEntry) {
    const startIndex = vocabularyEntries.findIndex(
      (vocabularyEntry) => vocabularyEntry.id === entry.id,
    );
    const entries = Array.from({ length: Math.min(5, vocabularyEntries.length) })
      .map((_, offset) => vocabularyEntries[(startIndex + offset) % vocabularyEntries.length])
      .filter(Boolean);

    setPracticeEntries(entries);
    setPracticeIndex(0);
    setIsExplanationVisible(false);
    setPracticeResults({});
  }

  function closeVocabularyPractice() {
    setPracticeEntries([]);
    setPracticeIndex(0);
    setIsExplanationVisible(false);
    setPracticeResults({});
  }

  function getProgressStatus(entry: VocabularyEntry): ProgressStatus {
    return syncedProgressStatuses[entry.id] ?? entry.progressStatus ?? "notStarted";
  }

  function answerPracticeCard(result: PracticeResult) {
    if (!activePracticeEntry) {
      return;
    }

    setPracticeResults((currentResults) => ({
      ...currentResults,
      [activePracticeEntry.id]: result,
    }));
    setPracticeIndex((currentIndex) => currentIndex + 1);
    setIsExplanationVisible(false);
  }

  function syncPracticeProgress() {
    setSyncedProgressStatuses((currentStatuses) => {
      const nextStatuses = { ...currentStatuses };

      practiceEntries.forEach((entry) => {
        const result = practiceResults[entry.id];

        if (result === "known") {
          nextStatuses[entry.id] = "remembered";
        }

        if (result === "unknown") {
          nextStatuses[entry.id] = "learning";
        }
      });

      return nextStatuses;
    });
    closeVocabularyPractice();
  }

  async function getAccessTokenForGeneration(): Promise<string | undefined> {
    if (auth.provider === "mock") {
      return "dev-access-token";
    }

    const oidcUser = await getCurrentOidcUser();

    return oidcUser?.access_token;
  }

  async function generatePersonalizedExample(entry: VocabularyEntry) {
    setGeneratingEntryId(entry.id);
    setGenerationErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[entry.id];
      return nextErrors;
    });

    try {
      const exampleSentence =
        await exampleSentenceRepository.generatePersonalizedExampleSentence({
          targetText: entry.targetText,
          userContextSummary: `${auth.user?.name ?? "A learner"} is practicing ${entry.targetText} in the ${course.title} course.`,
          accessToken: await getAccessTokenForGeneration(),
        });

      setGeneratedExampleSentences((currentExamples) => ({
        ...currentExamples,
        [entry.id]: [
          ...(currentExamples[entry.id] ?? []),
          exampleSentence,
        ],
      }));
    } catch (source) {
      setGenerationErrors((currentErrors) => ({
        ...currentErrors,
        [entry.id]:
          source instanceof Error
            ? source.message
            : "Failed to generate an example sentence.",
      }));
    } finally {
      setGeneratingEntryId(null);
    }
  }

  return (
    <section className="mt-8 rounded-[2rem] border border-amber-200 bg-white p-4 shadow-sm sm:p-6">
      <div className="flex gap-2 overflow-x-auto rounded-full bg-amber-100 p-2">
        {[
          { id: "vocabulary", label: "Vocabulary" },
          { id: "examples", label: "Examples" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveContentTab(tab.id as ContentTab)}
            className={`whitespace-nowrap rounded-full px-5 py-3 text-sm font-bold transition ${
              activeContentTab === tab.id
                ? "bg-amber-950 text-amber-50 shadow-sm"
                : "text-amber-800 hover:bg-amber-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-amber-600">
          {activeContentTab === "vocabulary" ? "Vocabulary" : "Examples"}
        </p>
        <p className="mt-2 text-sm leading-6 text-amber-800">
          {activeContentTab === "vocabulary"
            ? "Select an item to start a short practice session."
            : "Review basic and personalized example sentences by vocabulary item."}
        </p>
      </div>

      {activeContentTab === "vocabulary" && (
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {vocabularyEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => openVocabularyPractice(entry)}
              className="flex items-center justify-between gap-4 rounded-2xl border border-amber-100 bg-amber-50 p-4 text-left transition hover:-translate-y-0.5 hover:border-amber-300 hover:shadow-sm"
            >
              <div className="flex min-w-0 items-center gap-3">
                <VocabularyProgressMark status={getProgressStatus(entry)} />
                <div className="min-w-0">
                  <h3 className="truncate text-xl font-extrabold text-amber-950">
                    {entry.targetText}
                  </h3>
                </div>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-amber-700">
                {entry.kind}
              </span>
            </button>
          ))}
        </div>
      )}

      {activeContentTab === "examples" && (
        <div className="mt-6 space-y-4">
          {vocabularyEntries.map((entry) => {
            const exampleSentences = [
              ...(entry.exampleSentences ?? []),
              ...(generatedExampleSentences[entry.id] ?? []),
            ];
            const isGenerating = generatingEntryId === entry.id;

            return (
              <article
                key={entry.id}
                className="rounded-3xl border border-amber-100 bg-amber-50 p-5"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-xl font-extrabold text-amber-950">
                      {entry.targetText}
                    </h3>
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-amber-700">
                      {entry.kind}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => generatePersonalizedExample(entry)}
                    disabled={isGenerating}
                    className="rounded-full bg-amber-950 px-4 py-2 text-xs font-bold text-amber-50 transition hover:bg-amber-800 disabled:cursor-not-allowed disabled:bg-amber-300"
                  >
                    {isGenerating ? "Generating..." : "Generate personalized"}
                  </button>
                </div>

                {generationErrors[entry.id] && (
                  <p className="mt-3 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm leading-6 text-red-700">
                    {generationErrors[entry.id]}
                  </p>
                )}

                <div className="mt-4 rounded-2xl bg-white p-4">
                  <p className="text-xs font-bold uppercase tracking-[0.16em] text-amber-500">
                    Basic example
                  </p>
                  <p className="mt-2 text-sm leading-6 text-amber-950">
                    {entry.targetExampleSentence}
                  </p>
                  <p className="mt-1 text-sm leading-6 text-amber-700">
                    {entry.sourceExampleTranslation}
                  </p>
                </div>

                <div className="mt-3 space-y-3">
                  {exampleSentences.map((exampleSentence) => (
                    <div
                      key={exampleSentence.id}
                      className="rounded-2xl bg-white p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-xs font-bold uppercase tracking-[0.16em] text-amber-500">
                          Personalized example
                        </p>
                        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-700">
                          {exampleSentence.variant}
                        </span>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-amber-950">
                        {exampleSentence.targetSentence}
                      </p>
                      {exampleSentence.sourceTranslation && (
                        <p className="mt-1 text-sm leading-6 text-amber-700">
                          {exampleSentence.sourceTranslation}
                        </p>
                      )}
                    </div>
                  ))}
                  {exampleSentences.length ? null : (
                    <p className="rounded-2xl bg-white p-4 text-sm leading-6 text-amber-700">
                      Personalized examples have not been generated yet.
                    </p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {practiceEntries.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-amber-950/50 px-4 py-6">
          <div className="w-full max-w-xl rounded-[2rem] bg-white p-5 shadow-2xl sm:p-7">
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-amber-500">
                {isPracticeSummaryVisible
                  ? "Summary"
                  : `${practiceIndex + 1} / ${practiceEntries.length}`}
              </p>
              <button
                type="button"
                onClick={closeVocabularyPractice}
                className="rounded-full bg-amber-100 px-4 py-2 text-sm font-bold text-amber-800 transition hover:bg-amber-200"
              >
                Close
              </button>
            </div>

            {isPracticeSummaryVisible ? (
              <div className="mt-8 rounded-3xl bg-amber-50 p-6">
                <h3 className="text-2xl font-extrabold text-amber-950">
                  Practice complete
                </h3>
                <p className="mt-2 text-sm leading-6 text-amber-800">
                  結果を確認して、習得状態へ反映できます。
                </p>

                <div className="mt-6 grid grid-cols-2 gap-3">
                  <div className="rounded-2xl bg-white p-5">
                    <p className="text-xs font-bold uppercase tracking-[0.16em] text-amber-500">
                      Known
                    </p>
                    <p className="mt-2 text-3xl font-extrabold text-emerald-600">
                      {
                        Object.values(practiceResults).filter(
                          (result) => result === "known",
                        ).length
                      }
                    </p>
                  </div>
                  <div className="rounded-2xl bg-white p-5">
                    <p className="text-xs font-bold uppercase tracking-[0.16em] text-amber-500">
                      Need Review
                    </p>
                    <p className="mt-2 text-3xl font-extrabold text-amber-600">
                      {
                        Object.values(practiceResults).filter(
                          (result) => result === "unknown",
                        ).length
                      }
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={syncPracticeProgress}
                  className="mt-6 w-full rounded-full bg-amber-950 px-5 py-3 text-sm font-bold text-amber-50 transition hover:bg-amber-800"
                >
                  Sync progress
                </button>
              </div>
            ) : activePracticeEntry ? (
              <>
                <div className="mt-8 rounded-3xl bg-amber-50 p-6">
                  <div className="text-center">
                    <div className="flex justify-center">
                      <VocabularyProgressMark
                        status={getProgressStatus(activePracticeEntry)}
                      />
                    </div>
                    <p className="mt-6 text-sm font-bold uppercase tracking-[0.2em] text-amber-500">
                      Vocabulary
                    </p>
                    <h3 className="mt-3 text-4xl font-extrabold tracking-tight text-amber-950">
                      {activePracticeEntry.targetText}
                    </h3>
                    <p className="mt-3 text-sm font-bold text-amber-700">
                      {activePracticeEntry.kind}
                    </p>
                  </div>

                  {isExplanationVisible ? (
                    <div className="mt-7 space-y-4">
                      <div className="rounded-2xl bg-white p-4">
                        <p className="text-xs font-bold uppercase tracking-[0.16em] text-amber-500">
                          Meaning
                        </p>
                        <p className="mt-2 text-sm leading-6 text-amber-900">
                          {activePracticeEntry.sourceMeaning}
                        </p>
                      </div>
                      <div className="rounded-2xl bg-white p-4">
                        <p className="text-sm leading-6 text-amber-950">
                          {activePracticeEntry.targetExampleSentence}
                        </p>
                        <p className="mt-2 text-sm leading-6 text-amber-700">
                          {activePracticeEntry.sourceExampleTranslation}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-7 text-center text-sm leading-6 text-amber-800">
                      意味を思い出してから、解説を表示してください。
                    </p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => setIsExplanationVisible((isVisible) => !isVisible)}
                  className="mt-5 w-full rounded-full bg-amber-950 px-5 py-3 text-sm font-bold text-amber-50 transition hover:bg-amber-800"
                >
                  {isExplanationVisible ? "Hide explanation" : "Show explanation"}
                </button>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => answerPracticeCard("unknown")}
                    className="rounded-full border border-amber-200 px-5 py-3 text-sm font-bold text-amber-800 transition hover:bg-amber-50"
                  >
                    わからない
                  </button>
                  <button
                    type="button"
                    onClick={() => answerPracticeCard("known")}
                    className="rounded-full bg-emerald-500 px-5 py-3 text-sm font-bold text-white transition hover:bg-emerald-600"
                  >
                    わかる
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

function VocabularyProgressMark({
  status = "notStarted",
}: {
  status?: "notStarted" | "learning" | "remembered";
}) {
  if (status === "remembered") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500 text-sm font-extrabold text-white">
        ✓
      </span>
    );
  }

  if (status === "learning") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-amber-400 bg-white text-xs font-extrabold text-amber-600">
        …
      </span>
    );
  }

  return (
    <span className="h-7 w-7 rounded-full border-2 border-amber-200 bg-white" />
  );
}
