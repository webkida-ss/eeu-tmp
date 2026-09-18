"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AuthActionButton } from "@/features/auth/components/AuthActionButton";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { getCurrentOidcUser } from "@/features/auth/lib/oidcClient";
import {
  getLearnerProfileRepository,
  type LearnerProfileDraft,
} from "@/features/profile/repositories/learnerProfileRepository";

type CompletionCategory = {
  id: string;
  label: string;
  helper: string;
  score: number;
};

const initialLearnerProfileDraft: LearnerProfileDraft = {
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

const profileFields: Array<{
  id: keyof LearnerProfileDraft;
  label: string;
  placeholder: string;
  multiline?: boolean;
}> = [
  {
    id: "learningPurpose",
    label: "English goal",
    placeholder: "Example: I want to speak naturally while traveling.",
    multiline: true,
  },
  {
    id: "targetLevel",
    label: "Target level / exam",
    placeholder: "Example: TOEIC 800, CEFR B2, business small talk.",
  },
  {
    id: "deadline",
    label: "Target timing",
    placeholder: "Example: Before my summer trip.",
  },
  {
    id: "interests",
    label: "Interests and hobbies",
    placeholder: "Example: baseball, cafes, design, cooking.",
    multiline: true,
  },
  {
    id: "favoriteContent",
    label: "Favorite content",
    placeholder: "Example: podcasts, YouTube channels, books, games.",
    multiline: true,
  },
  {
    id: "dailyScenes",
    label: "Daily scenes",
    placeholder: "Example: commuting, shopping, meetings, family time.",
    multiline: true,
  },
  {
    id: "englishUseCases",
    label: "Where English should appear",
    placeholder: "Example: hotel check-in, Slack replies, restaurant orders.",
    multiline: true,
  },
  {
    id: "weakPoints",
    label: "Weak points",
    placeholder: "Example: articles, tense, word order, polite requests.",
    multiline: true,
  },
  {
    id: "vocabularyFocus",
    label: "Words to practice more",
    placeholder: "Example: phrasal verbs, work verbs, travel adjectives.",
    multiline: true,
  },
];

export default function MyPage() {
  const { error, provider, status, user } = useAuth();
  const [learnerProfile, setLearnerProfile] = useState<LearnerProfileDraft>(
    initialLearnerProfileDraft,
  );
  const [profileStatus, setProfileStatus] = useState<
    "idle" | "loading" | "saving" | "saved" | "error"
  >("idle");
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const displayName = user?.name || "Signed-in learner";
  const initial = displayName.slice(0, 1).toUpperCase();
  const learnerProfileRepository = useMemo(
    () => getLearnerProfileRepository(),
    [],
  );
  const completionCategories = useMemo(
    () => buildCompletionCategories(learnerProfile),
    [learnerProfile],
  );
  const totalCompletion = Math.round(
    completionCategories.reduce((sum, category) => sum + category.score, 0) /
      completionCategories.length,
  );
  const nextCategory = completionCategories.reduce((currentLowest, category) =>
    category.score < currentLowest.score ? category : currentLowest,
  );

  function updateLearnerProfile(
    field: keyof LearnerProfileDraft,
    value: string,
  ) {
    setLearnerProfile((currentProfile) => ({
      ...currentProfile,
      [field]: value,
    }));
  }

  const getAccessTokenForProfile = useCallback(async (): Promise<
    string | undefined
  > => {
    if (provider === "mock") {
      return "dev-access-token";
    }

    const oidcUser = await getCurrentOidcUser();

    return oidcUser?.access_token;
  }, [provider]);

  async function saveLearnerProfile() {
    setProfileStatus("saving");
    setProfileMessage(null);

    try {
      const savedProfile = await learnerProfileRepository.saveLearnerProfile(
        learnerProfile,
        await getAccessTokenForProfile(),
      );

      setLearnerProfile(savedProfile);
      setProfileStatus("saved");
      setProfileMessage("Profile saved. Context Chick is storing the seasoning.");
    } catch (source) {
      setProfileStatus("error");
      setProfileMessage(
        source instanceof Error
          ? source.message
          : "Failed to save learner profile.",
      );
    }
  }

  useEffect(() => {
    if (!user) {
      return;
    }

    let isMounted = true;

    async function loadLearnerProfile() {
      setProfileStatus("loading");
      setProfileMessage(null);

      try {
        const profile = await learnerProfileRepository.getLearnerProfile(
          await getAccessTokenForProfile(),
        );

        if (!isMounted) {
          return;
        }

        setLearnerProfile(profile);
        setProfileStatus("idle");
      } catch (source) {
        if (!isMounted) {
          return;
        }

        setProfileStatus("error");
        setProfileMessage(
          source instanceof Error
            ? source.message
            : "Failed to load learner profile.",
        );
      }
    }

    void loadLearnerProfile();

    return () => {
      isMounted = false;
    };
  }, [getAccessTokenForProfile, learnerProfileRepository, user]);

  if (status === "loading") {
    return (
      <main className="min-h-screen bg-amber-50 px-6 py-10 text-amber-950">
        <section className="mx-auto flex min-h-[70vh] max-w-3xl items-center justify-center">
          <div className="rounded-3xl border border-amber-100 bg-white p-8 text-center shadow-sm">
            <p className="text-sm font-bold uppercase tracking-[0.28em] text-amber-500">
              My page
            </p>
            <h1 className="mt-4 text-3xl font-extrabold">Loading your session</h1>
            <p className="mt-3 text-amber-800">
              Checking your current Cognito session.
            </p>
          </div>
        </section>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen bg-amber-50 px-6 py-10 text-amber-950">
        <section className="mx-auto flex min-h-[70vh] max-w-3xl items-center justify-center">
          <div className="rounded-3xl border border-amber-100 bg-white p-8 text-center shadow-sm">
            <p className="text-sm font-bold uppercase tracking-[0.28em] text-amber-500">
              My page
            </p>
            <h1 className="mt-4 text-3xl font-extrabold">Sign in required</h1>
            <p className="mt-3 text-amber-800">
              Sign in with Google through Cognito to view your learner profile.
            </p>
            {error ? (
              <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-8 flex justify-center">
              <AuthActionButton />
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-amber-50 px-6 py-10 text-amber-950">
      <div className="mx-auto max-w-5xl">
        <header className="flex items-center justify-between gap-4">
          <Link
            href="/"
            className="text-sm font-semibold text-amber-700 transition-colors hover:text-amber-500"
          >
            Back to home
          </Link>
          <AuthActionButton />
        </header>

        <section className="mt-12 overflow-hidden rounded-4xl border border-amber-200 bg-white shadow-sm">
          <div className="bg-amber-400 px-8 py-10 sm:px-10">
            <p className="text-sm font-bold uppercase tracking-[0.28em] text-amber-900">
              My page
            </p>
            <div className="mt-6 flex flex-col gap-6 sm:flex-row sm:items-center">
              <div className="flex size-24 items-center justify-center rounded-full border-4 border-amber-100 bg-amber-950 text-4xl font-black text-amber-50 shadow-lg">
                {initial}
              </div>
              <div>
                <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
                  {displayName}
                </h1>
                <p className="mt-3 text-lg font-semibold text-amber-900">
                  {user.email || "Email is not available yet"}
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-6 p-8 sm:grid-cols-2 sm:p-10">
            <ProfileItem label="App user ID" value={user.id} />
            <ProfileItem label="Auth provider" value={provider} />
            <ProfileItem label="Display name" value={displayName} />
            <ProfileItem label="Email" value={user.email || "Not available"} />
          </div>
        </section>

        <section className="mt-8 overflow-hidden rounded-[2.25rem] border border-amber-200 bg-white shadow-sm">
          <div className="grid gap-0 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="relative overflow-hidden bg-amber-100 p-7 sm:p-9">
              <div className="absolute -right-12 -top-14 size-40 rounded-full bg-amber-300/40" />
              <div className="absolute -bottom-20 left-10 size-52 rounded-full bg-orange-200/50" />
              <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center">
                <div className="flex size-28 shrink-0 rotate-[-4deg] items-center justify-center rounded-4xl border-4 border-amber-50 bg-amber-950 text-6xl shadow-xl">
                  🐣
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-black uppercase tracking-[0.28em] text-amber-700">
                    Context Chick
                  </p>
                  <h2 className="mt-3 text-4xl font-black tracking-tight text-amber-950 sm:text-5xl">
                    {totalCompletion}% seasoned
                  </h2>
                  <div className="mt-5 h-5 overflow-hidden rounded-full border-2 border-amber-50 bg-amber-200 shadow-inner">
                    <div
                      className="h-full rounded-full bg-linear-to-r from-amber-500 via-orange-400 to-orange-500 transition-all"
                      style={{ width: `${totalCompletion}%` }}
                    />
                  </div>
                  <p className="mt-4 max-w-xl text-sm font-bold leading-6 text-amber-800">
                    Feed the chick with your real-life context. The fuller this
                    gets, the less your AI examples taste like plain textbook
                    soup.
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-amber-950 p-7 text-amber-50 sm:p-9">
              <p className="text-xs font-black uppercase tracking-[0.28em] text-amber-300">
                Next best fill
              </p>
              <h3 className="mt-3 text-3xl font-black">
                Add more {nextCategory.label.toLowerCase()}
              </h3>
              <p className="mt-4 leading-7 text-amber-100">
                This is the weakest seasoning right now. Filling it in helps AI
                make example sentences feel more like your day, your goals, and
                your actual words.
              </p>
              <button
                type="button"
                className="mt-6 rounded-full bg-amber-300 px-5 py-3 text-sm font-black text-amber-950 shadow-sm transition hover:-translate-y-0.5 hover:bg-amber-200"
              >
                Feed the chick
              </button>
            </div>
          </div>

          <div className="grid gap-4 border-t border-amber-100 bg-amber-50/70 p-5 sm:grid-cols-2 lg:grid-cols-4">
            {completionCategories.map((category) => (
              <CompletionCard key={category.id} category={category} />
            ))}
          </div>
        </section>

        <section className="mt-8 rounded-4xl border border-amber-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-sm font-black uppercase tracking-[0.24em] text-amber-500">
                Learner profile
              </p>
              <h2 className="mt-3 text-3xl font-black tracking-tight">
                Ingredients for better AI examples
              </h2>
              <p className="mt-3 max-w-2xl leading-7 text-amber-800">
                These notes will become the personal context behind generated
                example sentences. Save them here, and the backend will reuse
                them when AI creates examples for your vocabulary.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void saveLearnerProfile()}
              disabled={profileStatus === "saving" || profileStatus === "loading"}
              className="rounded-full bg-amber-950 px-6 py-3 text-sm font-black text-amber-50 shadow-sm transition hover:-translate-y-0.5 hover:bg-amber-800 disabled:cursor-not-allowed disabled:bg-amber-300 disabled:text-amber-800"
            >
              {profileStatus === "saving" ? "Saving..." : "Save profile draft"}
            </button>
          </div>
          {profileMessage ? (
            <p
              className={`mt-5 rounded-2xl px-4 py-3 text-sm font-bold ${
                profileStatus === "error"
                  ? "bg-red-50 text-red-700"
                  : "bg-emerald-50 text-emerald-700"
              }`}
            >
              {profileMessage}
            </p>
          ) : null}

          <div className="mt-7 grid gap-4 md:grid-cols-2">
            {profileFields.map((field) => (
              <ProfileField
                key={field.id}
                field={field}
                value={learnerProfile[field.id]}
                onChange={(value) => updateLearnerProfile(field.id, value)}
              />
            ))}
          </div>
        </section>

        <section className="mt-8 grid gap-6 md:grid-cols-2">
          <Link
            href="/learning-paths"
            className="rounded-3xl border border-amber-200 bg-white p-7 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
          >
            <p className="text-sm font-bold uppercase tracking-[0.24em] text-amber-500">
              Continue learning
            </p>
            <h2 className="mt-4 text-2xl font-extrabold">Open learning paths</h2>
            <p className="mt-3 leading-7 text-amber-800">
              Pick a path and continue practicing English through focused courses.
            </p>
          </Link>

          <div className="rounded-3xl border border-amber-200 bg-amber-100 p-7">
            <p className="text-sm font-bold uppercase tracking-[0.24em] text-amber-600">
              Session
            </p>
            <h2 className="mt-4 text-2xl font-extrabold">Cognito session active</h2>
            <p className="mt-3 leading-7 text-amber-800">
              This page is rendered from the frontend auth context after the
              backend session API maps your Cognito identity to an app user.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}

function buildCompletionCategories(
  profile: LearnerProfileDraft,
): CompletionCategory[] {
  return [
    {
      id: "goals",
      label: "Goals",
      helper: "Purpose, target level, and timing.",
      score: scoreFields([
        profile.learningPurpose,
        profile.targetLevel,
        profile.deadline,
      ]),
    },
    {
      id: "interests",
      label: "Interests",
      helper: "Topics that add personality.",
      score: scoreFields([profile.interests, profile.favoriteContent]),
    },
    {
      id: "daily-scenes",
      label: "Daily scenes",
      helper: "Places where examples should live.",
      score: scoreFields([profile.dailyScenes, profile.englishUseCases]),
    },
    {
      id: "weak-points",
      label: "Weak points",
      helper: "Practice targets for sharper examples.",
      score: scoreFields([profile.weakPoints, profile.vocabularyFocus]),
    },
  ];
}

function scoreFields(values: string[]): number {
  const filledCount = values.filter((value) => value.trim().length > 0).length;

  return Math.round((filledCount / values.length) * 100);
}

function CompletionCard({ category }: { category: CompletionCategory }) {
  return (
    <div className="rounded-3xl border border-amber-100 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-black text-amber-950">{category.label}</h3>
          <p className="mt-1 text-xs font-semibold leading-5 text-amber-700">
            {category.helper}
          </p>
        </div>
        <p className="rounded-full bg-amber-100 px-3 py-1 text-sm font-black text-amber-800">
          {category.score}%
        </p>
      </div>
      <div className="mt-4 h-3 overflow-hidden rounded-full bg-amber-100">
        <div
          className="h-full rounded-full bg-amber-500 transition-all"
          style={{ width: `${category.score}%` }}
        />
      </div>
    </div>
  );
}

function ProfileField({
  field,
  onChange,
  value,
}: {
  field: (typeof profileFields)[number];
  onChange: (value: string) => void;
  value: string;
}) {
  const inputClassName =
    "mt-2 w-full rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm font-semibold text-amber-950 outline-none transition placeholder:text-amber-400 focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100";

  return (
    <label className="rounded-3xl border border-amber-100 bg-white p-5 shadow-sm">
      <span className="text-xs font-black uppercase tracking-[0.18em] text-amber-500">
        {field.label}
      </span>
      {field.multiline ? (
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.placeholder}
          rows={4}
          className={inputClassName}
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.placeholder}
          className={inputClassName}
        />
      )}
    </label>
  );
}

function ProfileItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-3xl border border-amber-100 bg-amber-50 p-6">
      <p className="text-xs font-bold uppercase tracking-[0.22em] text-amber-500">
        {label}
      </p>
      <p className="mt-3 break-all text-lg font-bold text-amber-950">{value}</p>
    </div>
  );
}
