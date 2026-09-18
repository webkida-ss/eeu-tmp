export type VocabularyEntryKind =
  | "word"
  | "phrase"
  | "idiom"
  | "phrasalVerb"
  | "expression";

export type ExampleSentenceVariant = "curated" | "personalized";

export type ExampleSentencePersonalization = {
  contextSummary?: string;
  personalizedFromUserContextAt?: string;
};

export type ExampleSentence = {
  id: string;
  targetText: string;
  targetSentence: string;
  sourceTranslation: string;
  variant: ExampleSentenceVariant;
  personalization?: ExampleSentencePersonalization;
  usageNote?: string;
};

export type VocabularyEntry = {
  id: string;
  targetText: string;
  kind: VocabularyEntryKind;
  sourceMeaning: string;
  targetExampleSentence: string;
  sourceExampleTranslation: string;
  progressStatus?: "notStarted" | "learning" | "remembered";
  exampleSentences?: ExampleSentence[];
};

export type Unit = {
  id: string;
  title: string;
  description: string;
  targetSkill: string;
  durationMinutes: number;
  vocabularyEntries: VocabularyEntry[];
};

export type Course = {
  id: string;
  title: string;
  levelLabel: string;
  description: string;
  outcome: string;
  estimatedHours: number;
  units: Unit[];
};

export type LearningPath = {
  id: string;
  title: string;
  tagline: string;
  description: string;
  audience: string;
  courses: Course[];
};
