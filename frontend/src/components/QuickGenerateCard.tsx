'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Loader2, Info, ChevronDown, CheckCircle2, AlertCircle } from 'lucide-react';
import { api } from '../lib/api';

type AudienceType = 'primary' | 'middle_school' | 'high_school' | 'college' | 'adult';
type DifficultyPreset = 'Balanced' | 'Easy-heavy' | 'Hard-heavy' | 'Custom';

interface AudienceOption {
  id: AudienceType;
  label: string;
  sublabel: string;
  availableGrades: number[];
  defaultGrades: number[];
}

const AUDIENCE_OPTIONS: AudienceOption[] = [
  {
    id: 'primary',
    label: 'Primary School',
    sublabel: 'Grades 1–5 (Ages 6–11)',
    availableGrades: [1, 2, 3, 4, 5],
    defaultGrades: [3, 4, 5],
  },
  {
    id: 'middle_school',
    label: 'Middle School',
    sublabel: 'Grades 6–8 (Ages 11–14)',
    availableGrades: [6, 7, 8],
    defaultGrades: [6, 7, 8],
  },
  {
    id: 'high_school',
    label: 'High School',
    sublabel: 'Grades 9–12 (Ages 14–18)',
    availableGrades: [9, 10, 11, 12],
    defaultGrades: [11, 12],
  },
  {
    id: 'college',
    label: 'College / University',
    sublabel: 'Undergraduate & Higher Ed',
    availableGrades: [],
    defaultGrades: [],
  },
  {
    id: 'adult',
    label: 'Adults',
    sublabel: 'Adult Trivia & Corporate',
    availableGrades: [],
    defaultGrades: [],
  },
];

function getDistributionForPreset(preset: DifficultyPreset, count: number): { easy: number; medium: number; hard: number } {
  if (preset === 'Easy-heavy') {
    if (count === 10) return { easy: 6, medium: 3, hard: 1 };
    if (count === 20) return { easy: 12, medium: 6, hard: 2 };
    const easy = Math.max(1, Math.round(count * 0.6));
    const medium = Math.max(1, Math.round(count * 0.3));
    const hard = Math.max(0, count - easy - medium);
    return { easy, medium, hard };
  }

  if (preset === 'Hard-heavy') {
    if (count === 10) return { easy: 1, medium: 3, hard: 6 };
    if (count === 20) return { easy: 2, medium: 6, hard: 12 };
    const hard = Math.max(1, Math.round(count * 0.6));
    const medium = Math.max(1, Math.round(count * 0.3));
    const easy = Math.max(0, count - hard - medium);
    return { easy, medium, hard };
  }

  // Balanced default
  if (count === 10) return { easy: 3, medium: 5, hard: 2 };
  if (count === 20) return { easy: 5, medium: 10, hard: 5 };
  if (count === 5) return { easy: 1, medium: 3, hard: 1 };
  if (count === 15) return { easy: 4, medium: 8, hard: 3 };

  const easy = Math.max(1, Math.round(count * 0.25));
  const hard = Math.max(1, Math.round(count * 0.25));
  const medium = Math.max(0, count - easy - hard);
  return { easy, medium, hard };
}

export default function QuickGenerateCard() {
  const router = useRouter();
  const [topic, setTopic] = useState('Australian History');
  const [audienceType, setAudienceType] = useState<AudienceType>('primary');
  const [selectedGrades, setSelectedGrades] = useState<number[]>([3, 4, 5]);
  const [questionCount, setQuestionCount] = useState<number>(10);

  // Difficulty Distribution
  const [difficultyPreset, setDifficultyPreset] = useState<DifficultyPreset>('Balanced');
  const [easyCount, setEasyCount] = useState<number>(3);
  const [mediumCount, setMediumCount] = useState<number>(5);
  const [hardCount, setHardCount] = useState<number>(2);

  const [questionTypes, setQuestionTypes] = useState<string[]>(['SLIDE_QA']);
  const [generationMode, setGenerationMode] = useState('NEW');
  const [style, setStyle] = useState('QSHALA_HISTORICAL');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const topicPresets = [
    'Australian History',
    'World Wonders',
    'Space & Astronomy',
    'Science',
    'Aboriginal Culture',
  ];

  const currentAudience = AUDIENCE_OPTIONS.find((a) => a.id === audienceType) || AUDIENCE_OPTIONS[0];
  const totalAllocated = easyCount + mediumCount + hardCount;
  const isDistributionValid = totalAllocated === questionCount;

  const handleAudienceChange = (newAudienceId: AudienceType) => {
    setAudienceType(newAudienceId);
    const targetAudience = AUDIENCE_OPTIONS.find((a) => a.id === newAudienceId);
    if (targetAudience) {
      setSelectedGrades(targetAudience.defaultGrades);
    }
  };

  const toggleGrade = (g: number) => {
    if (selectedGrades.includes(g)) {
      if (selectedGrades.length > 1) {
        setSelectedGrades(selectedGrades.filter((item) => item !== g));
      }
    } else {
      setSelectedGrades([...selectedGrades, g].sort((a, b) => a - b));
    }
  };

  const setGradeRange = (grades: number[]) => {
    setSelectedGrades(grades);
  };

  const handleQuestionCountChange = (newCount: number) => {
    setQuestionCount(newCount);
    if (difficultyPreset !== 'Custom') {
      const dist = getDistributionForPreset(difficultyPreset, newCount);
      setEasyCount(dist.easy);
      setMediumCount(dist.medium);
      setHardCount(dist.hard);
    }
  };

  const handlePresetChange = (preset: DifficultyPreset) => {
    setDifficultyPreset(preset);
    if (preset !== 'Custom') {
      const dist = getDistributionForPreset(preset, questionCount);
      setEasyCount(dist.easy);
      setMediumCount(dist.medium);
      setHardCount(dist.hard);
    }
  };

  const handleDistributionInput = (type: 'easy' | 'medium' | 'hard', val: number) => {
    setDifficultyPreset('Custom');
    const safeVal = Math.max(0, isNaN(val) ? 0 : val);
    if (type === 'easy') setEasyCount(safeVal);
    if (type === 'medium') setMediumCount(safeVal);
    if (type === 'hard') setHardCount(safeVal);
  };

  const toggleQuestionType = (type: string) => {
    if (questionTypes.includes(type)) {
      if (questionTypes.length > 1) {
        setQuestionTypes(questionTypes.filter((t) => t !== type));
      }
    } else {
      setQuestionTypes([...questionTypes, type]);
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) {
      setError('Please select or enter a quiz topic');
      return;
    }

    if (!isDistributionValid) {
      setError(`Difficulty distribution total (${totalAllocated}) must equal question count (${questionCount}).`);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const hasGrades = currentAudience.availableGrades.length > 0 && selectedGrades.length > 0;
      const minG = hasGrades ? Math.min(...selectedGrades) : undefined;
      const maxG = hasGrades ? Math.max(...selectedGrades) : undefined;
      const gradeSuffix = minG && maxG ? ` (Grades ${minG}–${maxG})` : ` (${currentAudience.label})`;
      const promptSummary = `Create a ${questionCount}-question quiz on ${topic} for ${currentAudience.label}${gradeSuffix} with distribution: ${easyCount} Easy, ${mediumCount} Medium, ${hardCount} Hard.`;

      const quiz = await api.generateQuiz({
        topic: topic.trim(),
        audience_type: audienceType,
        grades: hasGrades ? selectedGrades : undefined,
        grade_min: minG,
        grade_max: maxG,
        difficulty: difficultyPreset,
        difficulty_distribution: {
          easy: easyCount,
          medium: mediumCount,
          hard: hardCount,
        },
        question_count: questionCount,
        question_types: questionTypes,
        generation_mode: generationMode,
        style,
        raw_prompt: promptSummary,
      });

      router.push(`/quizzes/${quiz.id}`);
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Failed to generate quiz. Please verify the knowledge base.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-6 sm:p-7 shadow-sm shadow-slate-100/50">
      {/* Header */}
      <div className="border-b border-slate-100 pb-4 mb-6">
        <h2 className="text-[20px] font-bold tracking-tight text-slate-900">Create a Quiz</h2>
        <p className="mt-1 text-[13px] text-slate-500 font-normal leading-relaxed">
          Configure audience calibration and difficulty distribution to generate fresh questions grounded in your knowledge base.
        </p>
      </div>

      {error && (
        <div className="mb-5 rounded-lg border border-red-200 bg-red-50 p-3 text-[13px] text-red-700 flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleGenerate} className="space-y-6">
        {/* Row 1: Topic */}
        <div>
          <label className="block text-[13px] font-semibold text-slate-700 mb-1.5">Topic</label>
          <div className="relative">
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. Australian History, World Geography, Science"
              className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] font-normal text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 transition-all"
            />
          </div>

          {/* Suggested Chips */}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {topicPresets.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setTopic(preset)}
                className={`rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors cursor-pointer ${
                  topic === preset
                    ? 'bg-blue-50 text-blue-700 border border-blue-200 font-semibold'
                    : 'bg-slate-50 text-slate-500 hover:text-slate-800 border border-slate-100'
                }`}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>

        {/* Row 2: Hierarchical Audience & Education Level */}
        <div className="rounded-lg border border-slate-200/90 bg-slate-50/40 p-4 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-start">
            {/* Audience Dropdown */}
            <div>
              <label className="block text-[13px] font-semibold text-slate-700 mb-1.5">
                Target Audience / Education Level
              </label>
              <div className="relative">
                <select
                  value={audienceType}
                  onChange={(e) => handleAudienceChange(e.target.value as AudienceType)}
                  className="w-full appearance-none rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[13.5px] font-normal text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-9 cursor-pointer"
                >
                  {AUDIENCE_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label} — {opt.sublabel}
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-3 top-3 h-4 w-4 text-slate-400 pointer-events-none" />
              </div>
            </div>

            {/* Conditional Grade Selector or Audience Description */}
            <div>
              {currentAudience.availableGrades.length > 0 ? (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-[13px] font-semibold text-slate-700">
                      Select Grades ({currentAudience.label})
                    </label>
                    {/* Quick Range Presets */}
                    {audienceType === 'primary' && (
                      <div className="flex gap-1.5 items-center">
                        <button
                          type="button"
                          onClick={() => setGradeRange([1, 2])}
                          className="text-[12px] text-blue-600 hover:underline font-medium cursor-pointer"
                        >
                          Grades 1–2
                        </button>
                        <span className="text-[11px] text-slate-300">·</span>
                        <button
                          type="button"
                          onClick={() => setGradeRange([3, 4, 5])}
                          className="text-[12px] text-blue-600 hover:underline font-medium cursor-pointer"
                        >
                          Grades 3–5
                        </button>
                      </div>
                    )}
                    {audienceType === 'high_school' && (
                      <div className="flex gap-1.5 items-center">
                        <button
                          type="button"
                          onClick={() => setGradeRange([9, 10])}
                          className="text-[12px] text-blue-600 hover:underline font-medium cursor-pointer"
                        >
                          Grades 9–10
                        </button>
                        <span className="text-[11px] text-slate-300">·</span>
                        <button
                          type="button"
                          onClick={() => setGradeRange([11, 12])}
                          className="text-[12px] text-blue-600 hover:underline font-medium cursor-pointer"
                        >
                          Grades 11–12
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {currentAudience.availableGrades.map((g) => {
                      const isSelected = selectedGrades.includes(g);
                      return (
                        <button
                          key={g}
                          type="button"
                          onClick={() => toggleGrade(g)}
                          className={`h-9 min-w-10 px-2.5 rounded-lg border text-[13px] font-medium transition-all cursor-pointer ${
                            isSelected
                              ? 'border-blue-600 bg-blue-50/90 text-blue-700 font-semibold shadow-xs'
                              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                          }`}
                        >
                          Grade {g}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="h-full flex flex-col justify-center pt-2 sm:pt-6">
                  <div className="rounded-lg border border-slate-200/60 bg-white/80 px-3.5 py-2 text-[13px] text-slate-600 leading-relaxed">
                    <span className="font-semibold text-slate-800">
                      {currentAudience.label} Audience:
                    </span>{' '}
                    {audienceType === 'college'
                      ? 'Questions calibrated for tertiary students with academic rigor and multi-step critical synthesis.'
                      : 'Questions designed for adult pub-trivia, tournaments, and corporate engagement.'}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Row 3: Question Count & Difficulty Distribution */}
        <div className="rounded-lg border border-slate-200/90 bg-white p-4 space-y-4">
          {/* Top Bar: Question Count + Distribution Presets */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-end pb-3 border-b border-slate-100">
            {/* Number of Questions */}
            <div>
              <label className="block text-[13px] font-semibold text-slate-700 mb-1.5">
                Number of Questions
              </label>
              <div className="flex gap-2">
                {[5, 10, 15, 20].map((num) => (
                  <button
                    key={num}
                    type="button"
                    onClick={() => handleQuestionCountChange(num)}
                    className={`flex-1 rounded-lg border py-2 text-[13px] font-medium transition-all cursor-pointer ${
                      questionCount === num
                        ? 'border-blue-600 bg-blue-50/80 text-blue-700 font-semibold'
                        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    {num} Qs
                  </button>
                ))}
              </div>
            </div>

            {/* Distribution Presets */}
            <div>
              <label className="block text-[13px] font-semibold text-slate-700 mb-1.5">
                Difficulty Presets
              </label>
              <div className="grid grid-cols-4 gap-1 rounded-lg border border-slate-200 bg-slate-50/60 p-1">
                {(['Balanced', 'Easy-heavy', 'Hard-heavy', 'Custom'] as DifficultyPreset[]).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => handlePresetChange(p)}
                    className={`rounded-md py-1.5 text-[12px] font-medium transition-all cursor-pointer truncate ${
                      difficultyPreset === p
                        ? 'bg-white text-blue-700 font-semibold shadow-xs border border-slate-200/80'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Editable Distribution Inputs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[13px] font-semibold text-slate-700">
                Difficulty Distribution Allocation
              </span>
              <div className="flex items-center gap-1.5 text-[12px]">
                {isDistributionValid ? (
                  <span className="flex items-center gap-1 font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200/60">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Total: {totalAllocated} / {questionCount} ✓
                  </span>
                ) : (
                  <span className="flex items-center gap-1 font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200/60">
                    <AlertCircle className="h-3.5 w-3.5 text-amber-600" />
                    Total: {totalAllocated} / {questionCount} (Must equal {questionCount})
                  </span>
                )}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {/* Easy Input */}
              <div className="rounded-lg border border-slate-200 bg-slate-50/30 p-2.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[13px] font-semibold text-emerald-700">Easy</span>
                  <span className="text-[11px] text-slate-400 font-medium">
                    {Math.round((easyCount / (questionCount || 1)) * 100)}%
                  </span>
                </div>
                <input
                  type="number"
                  min="0"
                  max={questionCount}
                  value={easyCount}
                  onChange={(e) => handleDistributionInput('easy', parseInt(e.target.value))}
                  className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[14px] font-semibold text-slate-900 focus:border-emerald-500 focus:outline-none"
                />
              </div>

              {/* Medium Input */}
              <div className="rounded-lg border border-slate-200 bg-slate-50/30 p-2.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[13px] font-semibold text-blue-700">Medium</span>
                  <span className="text-[11px] text-slate-400 font-medium">
                    {Math.round((mediumCount / (questionCount || 1)) * 100)}%
                  </span>
                </div>
                <input
                  type="number"
                  min="0"
                  max={questionCount}
                  value={mediumCount}
                  onChange={(e) => handleDistributionInput('medium', parseInt(e.target.value))}
                  className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[14px] font-semibold text-slate-900 focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Hard Input */}
              <div className="rounded-lg border border-slate-200 bg-slate-50/30 p-2.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[13px] font-semibold text-purple-700">Hard</span>
                  <span className="text-[11px] text-slate-400 font-medium">
                    {Math.round((hardCount / (questionCount || 1)) * 100)}%
                  </span>
                </div>
                <input
                  type="number"
                  min="0"
                  max={questionCount}
                  value={hardCount}
                  onChange={(e) => handleDistributionInput('hard', parseInt(e.target.value))}
                  className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[14px] font-semibold text-slate-900 focus:border-purple-500 focus:outline-none"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Row 4: Question & Slide Format */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-[13px] font-semibold text-slate-700">Quiz Question Format</label>
            <span className="text-[12px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">
              QShala Signature: Question & Next Slide Answer + Explanation
            </span>
          </div>
          <div className="rounded-lg border border-slate-200/80 bg-slate-50/50 p-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-[13px]">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-100 text-blue-700 font-bold text-[12px]">
                Q&A
              </div>
              <div>
                <span className="font-semibold text-slate-900 block">Slide Pair Presentation (Question → Answer Slide)</span>
                <span className="text-[12px] text-slate-500 font-normal">
                  Slide 1 displays the curiosity-driven question; Slide 2 reveals the answer and educational backstory (no MCQs).
                </span>
              </div>
            </div>
            <span className="shrink-0 text-[11px] font-bold uppercase tracking-wider text-slate-600 bg-white border border-slate-200 px-2.5 py-1 rounded-md">
              Active Format
            </span>
          </div>
        </div>

        {/* Row 5: Generation Mode & Style */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 pt-1">
          <div>
            <label className="block text-[13px] font-semibold text-slate-700 mb-1.5">
              Generation Mode
            </label>
            <div className="relative">
              <select
                value={generationMode}
                onChange={(e) => setGenerationMode(e.target.value)}
                className="w-full appearance-none rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[13.5px] font-normal text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-8 cursor-pointer"
              >
                <option value="NEW">New (Fresh synthesis from knowledge base)</option>
                <option value="REMIX">Remix (Pivot perspective of historical items)</option>
                <option value="HISTORICAL">Historical (Curate directly from archives)</option>
                <option value="SIMILAR">Similar (Sibling questions mirroring structure)</option>
              </select>
              <ChevronDown className="absolute right-2.5 top-3 h-3.5 w-3.5 text-slate-400 pointer-events-none" />
            </div>
          </div>

          <div>
            <label className="block text-[13px] font-semibold text-slate-700 mb-1.5">Style</label>
            <div className="relative">
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="w-full appearance-none rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[13.5px] font-normal text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-8 cursor-pointer"
              >
                <option value="QSHALA_HISTORICAL">QShala Historical Style</option>
                <option value="COMPETITION_TOURNAMENT">Tournament Finals (Challenging)</option>
                <option value="PRIMARY_EXPLORERS">Junior Explorers (Engaging & Direct)</option>
              </select>
              <ChevronDown className="absolute right-2.5 top-3 h-3.5 w-3.5 text-slate-400 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* Footer: Info Note & Primary Action */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-4 border-t border-slate-100">
          <div className="flex items-start gap-2 max-w-md text-[13px] text-slate-500 font-normal leading-relaxed">
            <Info className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
            <span>
              We'll search the QShala knowledge base to find relevant material and generate fresh, age-calibrated questions.
            </span>
          </div>

          <button
            type="submit"
            disabled={loading || !isDistributionValid}
            className="w-full sm:w-auto flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-[14px] font-semibold text-white shadow-sm shadow-blue-500/20 hover:bg-blue-700 active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer shrink-0"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Searching & Generating...</span>
              </>
            ) : (
              <>
                <span>Generate Quiz</span>
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
