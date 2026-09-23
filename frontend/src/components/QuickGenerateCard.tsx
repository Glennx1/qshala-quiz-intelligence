'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  Loader2,
  Info,
  ChevronDown,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Database,
  Layers,
  BookOpen,
} from 'lucide-react';
import { api } from '../lib/api';
import { TopicItem, TopicSummary } from '../lib/types';

type AudienceType = 'primary' | 'middle_school' | 'high_school' | 'college' | 'adult';
type DifficultyPreset = 'Balanced' | 'Easy-heavy' | 'Hard-heavy' | 'Custom';
type GenerationMode = 'HISTORICAL' | 'NEW' | 'REMIX' | 'SIMILAR';

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

  // Topic Predictive State
  const [topic, setTopic] = useState('Australian History');
  const [subtopic, setSubtopic] = useState('');
  const [topicsList, setTopicsList] = useState<TopicItem[]>([]);
  const [filteredTopics, setFilteredTopics] = useState<TopicItem[]>([]);
  const [showTopicDropdown, setShowTopicDropdown] = useState(false);
  const [topicSummary, setTopicSummary] = useState<TopicSummary | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Audience & Grades
  const [audienceType, setAudienceType] = useState<AudienceType>('primary');
  const [selectedGrades, setSelectedGrades] = useState<number[]>([3, 4, 5]);
  const [questionCount, setQuestionCount] = useState<number>(10);

  // Difficulty Distribution
  const [difficultyPreset, setDifficultyPreset] = useState<DifficultyPreset>('Balanced');
  const [easyCount, setEasyCount] = useState<number>(3);
  const [mediumCount, setMediumCount] = useState<number>(5);
  const [hardCount, setHardCount] = useState<number>(2);

  // Mode & Format
  const [generationMode, setGenerationMode] = useState<GenerationMode>('HISTORICAL');
  const [questionTypes, setQuestionTypes] = useState<string[]>(['SLIDE_QA']);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load topics from vault on mount
  useEffect(() => {
    api.getTopics()
      .then((list) => {
        setTopicsList(list);
        setFilteredTopics(list);
      })
      .catch((err) => console.error('Error fetching vault topics:', err));
  }, []);

  // Update topic summary whenever selected topic matches an indexed topic
  useEffect(() => {
    if (topic.trim()) {
      api.getTopicSummary(topic.trim())
        .then((summary) => setTopicSummary(summary))
        .catch(() => setTopicSummary(null));
    } else {
      setTopicSummary(null);
    }
  }, [topic]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowTopicDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleTopicInputChange = (val: string) => {
    setTopic(val);
    if (!val.trim()) {
      setFilteredTopics(topicsList);
    } else {
      const q = val.toLowerCase();
      setFilteredTopics(topicsList.filter((t) => t.topic.toLowerCase().includes(q)));
    }
    setShowTopicDropdown(true);
  };

  const handleSelectTopic = (selected: string) => {
    setTopic(selected);
    setShowTopicDropdown(false);
  };

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
        subtopic: subtopic.trim() || undefined,
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
        style: 'QSHALA_HISTORICAL',
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
      <form onSubmit={handleGenerate} className="space-y-6">
        {/* Section 1: Predictive Topic Input with Vault Auto-Detection */}
        <div className="space-y-2" ref={dropdownRef}>
          <div className="flex items-center justify-between">
            <label className="text-[13px] font-semibold text-slate-800">
              Quiz Topic
            </label>
            <span className="text-[12px] text-slate-400 font-normal">
              Type to search or predict from Vault
            </span>
          </div>

          <div className="relative">
            <input
              type="text"
              value={topic}
              onChange={(e) => handleTopicInputChange(e.target.value)}
              onFocus={() => setShowTopicDropdown(true)}
              placeholder="e.g. Australian History, World Geography, Science & Nature"
              className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-[14px] font-normal text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />

            {showTopicDropdown && filteredTopics.length > 0 && (
              <div className="absolute z-20 left-0 right-0 mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg py-1">
                <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400 border-b border-slate-100">
                  Predicted Vault Topics ({filteredTopics.length})
                </div>
                {filteredTopics.map((t) => (
                  <button
                    key={t.topic}
                    type="button"
                    onClick={() => handleSelectTopic(t.topic)}
                    className="w-full text-left px-3.5 py-2 hover:bg-slate-50 flex items-center justify-between text-[13px] text-slate-800 cursor-pointer"
                  >
                    <span className="font-medium">{t.topic}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                      {t.count} questions
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Live Topic Intelligence Badge */}
          {topicSummary && topicSummary.total_questions > 0 ? (
            <div className="rounded-lg bg-blue-50/60 border border-blue-100 p-3 text-[12px] space-y-1.5">
              <div className="flex items-center justify-between font-semibold text-blue-900">
                <span className="flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5 text-blue-600" />
                  Vault Intelligence: {topicSummary.total_questions} Questions Available
                </span>
                <span className="text-[11px] text-blue-600 font-medium">
                  Grades {topicSummary.grade_min}–{topicSummary.grade_max}
                </span>
              </div>
              <div className="flex items-center gap-3 text-slate-600">
                <span>Easy: <strong className="text-emerald-700">{topicSummary.difficulty_breakdown.Easy || 0}</strong></span>
                <span>Medium: <strong className="text-amber-700">{topicSummary.difficulty_breakdown.Medium || 0}</strong></span>
                <span>Hard: <strong className="text-purple-700">{topicSummary.difficulty_breakdown.Hard || 0}</strong></span>
              </div>
              {topicSummary.subtopics && topicSummary.subtopics.length > 0 && (
                <div className="flex flex-wrap items-center gap-1 pt-1">
                  <span className="text-slate-400 text-[11px]">Subtopics:</span>
                  {topicSummary.subtopics.map((sub) => (
                    <button
                      key={sub}
                      type="button"
                      onClick={() => setSubtopic(subtopic === sub ? '' : sub)}
                      className={`px-1.5 py-0.5 rounded text-[10.5px] font-medium border cursor-pointer ${
                        subtopic === sub
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100'
                      }`}
                    >
                      {sub}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            topic.trim() && (
              <p className="text-[11.5px] text-amber-600 flex items-center gap-1">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                <span>Novel topic: AI generator will synthesize grounded questions if vault has few matches.</span>
              </p>
            )
          )}
        </div>

        {/* Section 2: Generation Mode Selector */}
        <div className="space-y-2">
          <label className="text-[13px] font-semibold text-slate-800">
            Generation Strategy
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              {
                id: 'HISTORICAL',
                label: 'Vault Curation',
                desc: 'Compile real tournament slide pairs',
              },
              {
                id: 'NEW',
                label: 'AI Fresh',
                desc: 'Craft novel questions from facts',
              },
              {
                id: 'REMIX',
                label: 'AI Remix',
                desc: 'Reimagined angles & reverse clues',
              },
              {
                id: 'SIMILAR',
                label: 'AI Sibling',
                desc: 'Mirror tournament intellectual depth',
              },
            ].map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => setGenerationMode(m.id as GenerationMode)}
                className={`p-3 text-left rounded-lg border transition-all cursor-pointer ${
                  generationMode === m.id
                    ? 'border-blue-600 bg-blue-50/50 text-blue-900 shadow-xs'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                }`}
              >
                <div className="text-[12.5px] font-bold">{m.label}</div>
                <div className="text-[11px] text-slate-500 font-normal mt-0.5 leading-tight">{m.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Section 3: Audience Category */}
        <div className="space-y-2">
          <label className="text-[13px] font-semibold text-slate-800">
            Target Audience
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {AUDIENCE_OPTIONS.map((aud) => (
              <button
                key={aud.id}
                type="button"
                onClick={() => handleAudienceChange(aud.id)}
                className={`flex flex-col items-start p-2.5 rounded-lg border text-left transition-all cursor-pointer ${
                  audienceType === aud.id
                    ? 'border-blue-600 bg-blue-50/40 text-blue-900 shadow-xs'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50/50'
                }`}
              >
                <span className="text-[12.5px] font-semibold">{aud.label}</span>
                <span className="text-[10.5px] text-slate-400 font-normal mt-0.5 leading-tight">
                  {aud.sublabel}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Section 4: Grade Selector (for school audiences) */}
        {currentAudience.availableGrades.length > 0 && (
          <div className="space-y-2 rounded-lg border border-slate-100 bg-slate-50/60 p-3">
            <div className="flex items-center justify-between">
              <label className="text-[12.5px] font-semibold text-slate-700">
                School Grade Band
              </label>
              <div className="flex gap-1.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setSelectedGrades(currentAudience.availableGrades)}
                  className="text-blue-600 hover:underline cursor-pointer font-medium"
                >
                  All {currentAudience.label}
                </button>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              {currentAudience.availableGrades.map((g) => {
                const isSelected = selectedGrades.includes(g);
                return (
                  <button
                    key={g}
                    type="button"
                    onClick={() => toggleGrade(g)}
                    className={`h-8 w-11 rounded-md text-[12.5px] font-semibold transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-blue-600 text-white shadow-xs'
                        : 'bg-white border border-slate-200 text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    Gr {g}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Section 5: Question Count & Format */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-[13px] font-semibold text-slate-800">
              Question Count
            </label>
            <div className="flex gap-2">
              {[5, 10, 15, 20].map((cnt) => (
                <button
                  key={cnt}
                  type="button"
                  onClick={() => handleQuestionCountChange(cnt)}
                  className={`flex-1 py-1.5 rounded-md text-[13px] font-semibold transition-colors cursor-pointer ${
                    questionCount === cnt
                      ? 'bg-blue-600 text-white shadow-xs'
                      : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  {cnt} Qs
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-[13px] font-semibold text-slate-800">
              Presentation Format
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setQuestionTypes(['SLIDE_QA'])}
                className={`flex-1 py-1.5 rounded-md text-[12px] font-semibold transition-colors cursor-pointer ${
                  questionTypes.includes('SLIDE_QA') && !questionTypes.includes('MULTIPLE_CHOICE')
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                Q&A Slide Pairs
              </button>
              <button
                type="button"
                onClick={() => setQuestionTypes(['MULTIPLE_CHOICE'])}
                className={`flex-1 py-1.5 rounded-md text-[12px] font-semibold transition-colors cursor-pointer ${
                  questionTypes.includes('MULTIPLE_CHOICE')
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                4-Option MCQ
              </button>
            </div>
          </div>
        </div>

        {/* Section 6: Difficulty Distribution */}
        <div className="space-y-3 rounded-lg border border-slate-200/80 bg-white p-4">
          <div className="flex items-center justify-between">
            <label className="text-[13px] font-semibold text-slate-800">
              Difficulty Distribution
            </label>
            <span
              className={`text-[12px] font-semibold ${
                isDistributionValid ? 'text-emerald-600' : 'text-rose-600'
              }`}
            >
              {totalAllocated} / {questionCount} Allocated
            </span>
          </div>

          <div className="flex gap-2">
            {(['Balanced', 'Easy-heavy', 'Hard-heavy'] as DifficultyPreset[]).map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => handlePresetChange(preset)}
                className={`px-3 py-1 text-[12px] rounded-md font-medium transition-colors cursor-pointer ${
                  difficultyPreset === preset
                    ? 'bg-slate-900 text-white'
                    : 'border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100'
                }`}
              >
                {preset}
              </button>
            ))}
          </div>

          {/* Granular Sliders / Number Controls */}
          <div className="grid grid-cols-3 gap-3 pt-2">
            <div className="rounded-md border border-emerald-100 bg-emerald-50/30 p-2.5 text-center">
              <div className="text-[11px] font-bold text-emerald-700 uppercase tracking-wider">
                Easy
              </div>
              <input
                type="number"
                min={0}
                max={questionCount}
                value={easyCount}
                onChange={(e) => handleDistributionInput('easy', parseInt(e.target.value))}
                className="mt-1 w-full text-center text-[16px] font-bold text-slate-900 bg-transparent border-0 focus:ring-0"
              />
            </div>

            <div className="rounded-md border border-amber-100 bg-amber-50/30 p-2.5 text-center">
              <div className="text-[11px] font-bold text-amber-700 uppercase tracking-wider">
                Medium
              </div>
              <input
                type="number"
                min={0}
                max={questionCount}
                value={mediumCount}
                onChange={(e) => handleDistributionInput('medium', parseInt(e.target.value))}
                className="mt-1 w-full text-center text-[16px] font-bold text-slate-900 bg-transparent border-0 focus:ring-0"
              />
            </div>

            <div className="rounded-md border border-purple-100 bg-purple-50/30 p-2.5 text-center">
              <div className="text-[11px] font-bold text-purple-700 uppercase tracking-wider">
                Hard
              </div>
              <input
                type="number"
                min={0}
                max={questionCount}
                value={hardCount}
                onChange={(e) => handleDistributionInput('hard', parseInt(e.target.value))}
                className="mt-1 w-full text-center text-[16px] font-bold text-slate-900 bg-transparent border-0 focus:ring-0"
              />
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-[13px] text-rose-700 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Submit Action */}
        <button
          type="submit"
          disabled={loading || !isDistributionValid}
          className="w-full rounded-lg bg-blue-600 py-3 text-[14px] font-semibold text-white shadow-sm shadow-blue-500/20 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Compiling Quiz from Vault & Generating Slides...</span>
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              <span>
                {generationMode === 'HISTORICAL'
                  ? `Compile ${questionCount}-Question Quiz from Vault`
                  : `Generate ${questionCount}-Question AI Quiz`}
              </span>
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </form>
    </div>
  );
}
