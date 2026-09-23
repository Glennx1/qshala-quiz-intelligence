'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  Loader2,
  Info,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Database,
  Layers,
  BookOpen,
  Tag,
  X,
  Search,
  Plus,
  HelpCircle,
} from 'lucide-react';
import { api } from '../lib/api';
import { TopicItem, TopicSummary, TagItem, TagPreviewResponse } from '../lib/types';

type AudienceType = 'primary' | 'middle_school' | 'high_school' | 'college' | 'adult';
type DifficultyPreset = 'Balanced' | 'Easy-heavy' | 'Hard-heavy' | 'Custom';
type PersonalityType = 'CURIOSITY_STORYTELLER' | 'DETECTIVE_PUZZLER' | 'TOURNAMENT_PRO' | 'SOCRATIC_EXPLORER';

interface PersonalityOption {
  id: PersonalityType;
  title: string;
  role: string;
  description: string;
  badge: string;
  icon: string;
}

const PERSONALITY_OPTIONS: PersonalityOption[] = [
  {
    id: 'CURIOSITY_STORYTELLER',
    title: 'The Storyteller',
    role: 'Curiosity Coach',
    description: 'Engaging narrative clues, human interest trivia, and wonder-sparking backstory.',
    badge: 'Narrative',
    icon: '🌟',
  },
  {
    id: 'DETECTIVE_PUZZLER',
    title: 'The Detective',
    role: 'Puzzle Master',
    description: 'Progressive deduction clues, mystery framing, and lateral thinking challenges.',
    badge: 'Deductive',
    icon: '🔍',
  },
  {
    id: 'TOURNAMENT_PRO',
    title: 'Tournament Pro',
    role: 'Classic Buzzer',
    description: 'Crisp, high-energy, authoritative contest questions with unambiguous answers.',
    badge: 'Competitive',
    icon: '🏆',
  },
  {
    id: 'SOCRATIC_EXPLORER',
    title: 'Socratic Host',
    role: 'Discussion Lead',
    description: 'Inquiry-driven questions with classroom follow-up discussion prompts in speaker notes.',
    badge: 'Discussion',
    icon: '💡',
  },
];

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

  // Tags & Live Compilation State
  const [vaultTags, setVaultTags] = useState<TagItem[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [tagPreview, setTagPreview] = useState<TagPreviewResponse | null>(null);
  const [tagPreviewLoading, setTagPreviewLoading] = useState(false);
  const [showSampleQuestions, setShowSampleQuestions] = useState(false);

  // Personality State
  const [personality, setPersonality] = useState<PersonalityType>('CURIOSITY_STORYTELLER');

  // Difficulty Distribution
  const [difficultyPreset, setDifficultyPreset] = useState<DifficultyPreset>('Balanced');
  const [easyCount, setEasyCount] = useState<number>(3);
  const [mediumCount, setMediumCount] = useState<number>(5);
  const [hardCount, setHardCount] = useState<number>(2);

  // Format
  const [questionTypes, setQuestionTypes] = useState<string[]>(['SLIDE_QA']);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load topics and vault tags on mount
  useEffect(() => {
    api.getTopics()
      .then((list) => {
        setTopicsList(list);
        setFilteredTopics(list);
      })
      .catch((err) => console.error('Error fetching vault topics:', err));

    api.getVaultTags()
      .then((tags) => {
        setVaultTags(tags);
      })
      .catch((err) => console.error('Error fetching vault tags:', err));
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

  // Update live tag preview whenever topic or selected tags change
  useEffect(() => {
    if (topic.trim() || selectedTags.length > 0) {
      setTagPreviewLoading(true);
      api.getTagPreview(topic.trim() || undefined, selectedTags.length > 0 ? selectedTags : undefined)
        .then((res) => setTagPreview(res))
        .catch(() => setTagPreview(null))
        .finally(() => setTagPreviewLoading(false));
    } else {
      setTagPreview(null);
    }
  }, [topic, selectedTags]);

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

  const handleToggleTag = (tagName: string) => {
    if (selectedTags.includes(tagName)) {
      setSelectedTags(selectedTags.filter((t) => t !== tagName));
    } else {
      setSelectedTags([...selectedTags, tagName]);
    }
  };

  const handleAddCustomTag = (e?: React.KeyboardEvent | React.MouseEvent) => {
    if (e && 'key' in e && e.key !== 'Enter') return;
    if (e) e.preventDefault();
    const clean = tagInput.trim().replace(/^#/, '');
    if (clean && !selectedTags.includes(clean)) {
      setSelectedTags([...selectedTags, clean]);
      setTagInput('');
    }
  };

  const handleRemoveTag = (tagName: string) => {
    setSelectedTags(selectedTags.filter((t) => t !== tagName));
  };

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
    if (!topic.trim() && selectedTags.length === 0) {
      setError('Please select or enter a quiz topic or select at least one concept tag');
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
      const effectiveTopic = topic.trim() || (selectedTags.length > 0 ? selectedTags.join(', ') : 'General Knowledge');
      const tagSuffix = selectedTags.length > 0 ? ` [Tags: ${selectedTags.join(', ')}]` : '';
      const promptSummary = `Create a ${questionCount}-question quiz on ${effectiveTopic}${tagSuffix} for ${currentAudience.label}${gradeSuffix} with distribution: ${easyCount} Easy, ${mediumCount} Medium, ${hardCount} Hard.`;

      let mode = 'NEW';
      const availableCount = tagPreview ? tagPreview.total_available : (topicSummary ? topicSummary.total_questions : 0);
      if (availableCount >= questionCount) {
        mode = 'HISTORICAL';
      } else if (availableCount > 0) {
        mode = 'HYBRID';
      }

      const quiz = await api.generateQuiz({
        topic: effectiveTopic,
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
        generation_mode: mode,
        tags: selectedTags.length > 0 ? selectedTags : undefined,
        personality: personality,
        style: 'QSHALA_HISTORICAL',
        raw_prompt: promptSummary,
      });

      router.push(`/quizzes/${quiz.id}`);
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Failed to create quiz. Please verify the questions repository.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-6 sm:p-7 shadow-sm shadow-slate-100/50">
      <form onSubmit={handleGenerate} className="space-y-6">
        {/* Section 1: Dual-Axis Topic & Concept Tag Compilation */}
        <div className="space-y-4" ref={dropdownRef}>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-[13px] font-semibold text-slate-800">
                1. Macro Topic
              </label>
              <span className="text-[12px] text-slate-400 font-normal">
                Type to search available topics
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
                    Available Topics ({filteredTopics.length})
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

            {/* Subtopics from Topic Summary if available */}
            {topicSummary && topicSummary.subtopics && topicSummary.subtopics.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-slate-400 text-[11px] font-medium">Subtopics:</span>
                {topicSummary.subtopics.map((sub) => (
                  <button
                    key={sub}
                    type="button"
                    onClick={() => setSubtopic(subtopic === sub ? '' : sub)}
                    className={`px-2 py-0.5 rounded-md text-[11px] font-medium border transition-colors cursor-pointer ${
                      subtopic === sub
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                    }`}
                  >
                    {sub}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Micro Concept Tags Dual-Axis Filter */}
          <div className="space-y-2.5 rounded-lg border border-slate-200/90 bg-slate-50/50 p-3.5">
            <div className="flex items-center justify-between">
              <label className="text-[12.5px] font-semibold text-slate-800 flex items-center gap-1.5">
                <Tag className="h-3.5 w-3.5 text-blue-600" />
                <span>Micro Concept Tags (Cross-Topic Compilation)</span>
              </label>
              <span className="text-[11px] text-slate-400">
                Pull specific concepts across multiple decks
              </span>
            </div>

            {/* Selected Tags Chips */}
            {selectedTags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {selectedTags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 rounded-md bg-blue-100 text-blue-800 px-2.5 py-1 text-[12px] font-medium"
                  >
                    <span>#{tag}</span>
>>>>>>> 89331fc (feat: tag-to-topic quiz compilation, concept tag cloud, live vault preview, and quizmaster personalities)
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(tag)}
                      className="hover:text-blue-900 focus:outline-none cursor-pointer"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <button
                  type="button"
                  onClick={() => setSelectedTags([])}
                  className="text-[11px] text-slate-400 hover:text-slate-600 underline ml-1 cursor-pointer"
                >
                  Clear all
                </button>
              </div>
            )}

            {/* Tag Add / Search Input */}
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={handleAddCustomTag}
                  placeholder="Type concept tag (e.g. Captain Cook, Botany, Maritime) and press Enter..."
                  className="w-full rounded-md border border-slate-200 bg-white pl-8 pr-3 py-1.5 text-[12.5px] text-slate-800 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <button
                type="button"
                onClick={handleAddCustomTag}
                disabled={!tagInput.trim()}
                className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-slate-900 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Add Tag</span>
              </button>
            </div>

            {/* Concept Tag Cloud from Vault */}
            {vaultTags.length > 0 && (
              <div className="space-y-1 pt-1">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Popular Concept Tags in Vault:
                </span>
                <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto pt-0.5">
                  {vaultTags
                    .filter((t) => !tagInput.trim() || t.tag.toLowerCase().includes(tagInput.toLowerCase()))
                    .slice(0, 16)
                    .map((item) => {
                      const isSelected = selectedTags.includes(item.tag);
                      return (
                        <button
                          key={item.tag}
                          type="button"
                          onClick={() => handleToggleTag(item.tag)}
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium border transition-colors cursor-pointer ${
                            isSelected
                              ? 'bg-blue-600 text-white border-blue-600 shadow-xs'
                              : 'bg-white text-slate-700 border-slate-200 hover:border-blue-400 hover:bg-blue-50/40'
                          }`}
                        >
                          <span>#{item.tag}</span>
                          <span
                            className={`rounded-full px-1 text-[9.5px] ${
                              isSelected ? 'bg-blue-700 text-blue-100' : 'bg-slate-100 text-slate-500'
                            }`}
                          >
                            {item.count}
                          </span>
                        </button>
                      );
                    })}
                </div>
              </div>
            )}
          </div>

          {/* Live Dual-Axis Vault Compilation Preview */}
          {tagPreviewLoading ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3 flex items-center justify-center gap-2 text-[12px] text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              <span>Analyzing vault availability across topics and tags...</span>
            </div>
          ) : tagPreview ? (
            <div className="rounded-lg border border-blue-100 bg-blue-50/40 p-3.5 space-y-2.5 text-[12.5px]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 font-semibold text-slate-900">
                  <Database className="h-4 w-4 text-blue-600" />
                  <span>Vault Intelligence & Compilation Potential</span>
                </div>
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
                    tagPreview.total_available >= questionCount
                      ? 'bg-emerald-100 text-emerald-800'
                      : tagPreview.total_available > 0
                      ? 'bg-amber-100 text-amber-800'
                      : 'bg-blue-100 text-blue-800'
                  }`}
                >
                  {tagPreview.total_available >= questionCount ? (
                    <>
                      <CheckCircle2 className="h-3 w-3" />
                      <span>{tagPreview.total_available} Questions Ready (100% Vault)</span>
                    </>
                  ) : tagPreview.total_available > 0 ? (
                    <>
                      <Sparkles className="h-3 w-3" />
                      <span>{tagPreview.total_available} Vault + {Math.max(0, questionCount - tagPreview.total_available)} AI Hybrid</span>
                    </>
                  ) : (
                    <>
                      <Info className="h-3 w-3" />
                      <span>Novel Topic / Tag (AI Grounded)</span>
                    </>
                  )}
                </span>
              </div>

              {/* Exact vs Cross-Topic Breakdown */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
                <div className="rounded border border-slate-200/80 bg-white p-2">
                  <div className="text-[10.5px] text-slate-400 font-semibold uppercase">Exact Topic</div>
                  <div className="text-[15px] font-bold text-slate-800">{tagPreview.exact_matches_count}</div>
                </div>
                <div className="rounded border border-slate-200/80 bg-white p-2">
                  <div className="text-[10.5px] text-slate-400 font-semibold uppercase">Cross-Deck Tags</div>
                  <div className="text-[15px] font-bold text-blue-700">+{tagPreview.cross_topic_tag_matches_count}</div>
                </div>
                <div className="rounded border border-slate-200/80 bg-white p-2">
                  <div className="text-[10.5px] text-slate-400 font-semibold uppercase">Total Matched</div>
                  <div className="text-[15px] font-bold text-emerald-700">{tagPreview.total_available}</div>
                </div>
                <div className="rounded border border-slate-200/80 bg-white p-2">
                  <div className="text-[10.5px] text-slate-400 font-semibold uppercase">Vault Difficulty</div>
                  <div className="text-[11px] font-medium text-slate-600 mt-0.5">
                    E:{tagPreview.difficulty_breakdown.Easy || 0} M:{tagPreview.difficulty_breakdown.Medium || 0} H:{tagPreview.difficulty_breakdown.Hard || 0}
                  </div>
                </div>
              </div>

              {/* Sample Questions Peek Toggle */}
              {tagPreview.sample_questions && tagPreview.sample_questions.length > 0 && (
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() => setShowSampleQuestions(!showSampleQuestions)}
                    className="flex items-center gap-1 text-[11.5px] font-semibold text-blue-600 hover:text-blue-800 cursor-pointer"
                  >
                    <span>{showSampleQuestions ? 'Hide' : 'Peek'} Matched Vault Questions ({tagPreview.sample_questions.length})</span>
                    {showSampleQuestions ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </button>

                  {showSampleQuestions && (
                    <div className="mt-2 space-y-1.5 max-h-48 overflow-y-auto rounded border border-slate-200 bg-white p-2.5">
                      {tagPreview.sample_questions.map((sq, idx) => (
                        <div key={sq.id || idx} className="border-b border-slate-100 pb-1.5 last:border-b-0 last:pb-0 text-[11.5px]">
                          <div className="flex items-start justify-between gap-2">
                            <span className="font-medium text-slate-800 line-clamp-1">{sq.question_text}</span>
                            <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.2 text-[10px] font-semibold text-slate-600">
                              {sq.difficulty}
                            </span>
                          </div>
                          <div className="text-slate-500 text-[11px] flex items-center gap-2 mt-0.5">
                            <span>Ans: <strong className="text-slate-700">{sq.answer}</strong></span>
                            {sq.tags && sq.tags.length > 0 && (
                              <span className="text-blue-600">
                                {sq.tags.map((t) => `#${t}`).join(' ')}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            topic.trim() && (
              <p className="text-[11.5px] text-amber-600 flex items-center gap-1">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                <span>Novel topic: AI generator will synthesize grounded questions if few existing matches are found.</span>
              </p>
            )
          )}
        </div>

        {/* Section 2: Audience Category */}
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

        {/* Section 3: Quizmaster Host Personality */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[13px] font-semibold text-slate-800">
              Quizmaster Host Personality
            </label>
            <span className="text-[12px] text-slate-400 font-normal">
              Pedagogical tone & clue structure
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {PERSONALITY_OPTIONS.map((opt) => {
              const isSelected = personality === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setPersonality(opt.id)}
                  className={`flex flex-col text-left p-3 rounded-lg border transition-all cursor-pointer relative ${
                    isSelected
                      ? 'border-blue-600 bg-blue-50/50 shadow-xs ring-1 ring-blue-500'
                      : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50/50'
                  }`}
                >
                  <div className="flex items-center justify-between w-full mb-1">
                    <span className="text-lg">{opt.icon}</span>
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                        isSelected
                          ? 'bg-blue-600 text-white'
                          : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {opt.badge}
                    </span>
                  </div>

                  <div className="text-[13px] font-bold text-slate-900 leading-tight">
                    {opt.title}
                  </div>
                  <div className="text-[11px] font-semibold text-blue-600 mt-0.5">
                    {opt.role}
                  </div>
                  <p className="text-[11px] text-slate-500 font-normal mt-1.5 leading-snug line-clamp-3">
                    {opt.description}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

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
              <span>Compiling Quiz & Generating Slides...</span>
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              <span>
                {tagPreview && tagPreview.total_available >= questionCount
                  ? `Compile ${questionCount}-Question Quiz (100% Grounded)`
                  : tagPreview && tagPreview.total_available > 0
                  ? `Compile Hybrid Quiz (${tagPreview.total_available} Matched + ${Math.max(0, questionCount - tagPreview.total_available)} AI Grounded)`
                  : topicSummary && topicSummary.total_questions > 0
                  ? `Compile ${questionCount}-Question Quiz`
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
