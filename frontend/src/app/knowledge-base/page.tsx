'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Search,
  Filter,
  ExternalLink,
  Loader2,
  ArrowUpDown,
  Layers,
  Tag,
  Plus,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Volume2,
  Video,
  Image as ImageIcon,
  Copy,
  X
} from 'lucide-react';
import { api } from '../../lib/api';
import { HistoricalQuestion, TopicItem } from '../../lib/types';
import SlideViewerModal from '../../components/SlideViewerModal';
import TagManagerModal from '../../components/TagManagerModal';

function KnowledgeBaseContent() {
  const searchParams = useSearchParams();
  const initialTopic = searchParams.get('topic') || '';

  const [activeTab, setActiveTab] = useState<'all' | 'duplicates'>('all');
  const [duplicateCount, setDuplicateCount] = useState<number>(0);

  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState(initialTopic);
  const [subtopic, setSubtopic] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [difficulty, setDifficulty] = useState('');
  const [gradeMin, setGradeMin] = useState<number | ''>('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');

  const [topicsList, setTopicsList] = useState<TopicItem[]>([]);
  const [availableSubtopics, setAvailableSubtopics] = useState<string[]>([]);
  const [questions, setQuestions] = useState<HistoricalQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);
  const [selectedQuestionForTags, setSelectedQuestionForTags] = useState<HistoricalQuestion | null>(null);
  const [selectedDuplicateForReview, setSelectedDuplicateForReview] = useState<HistoricalQuestion | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  // Fetch topics list and duplicate count on mount
  useEffect(() => {
    const loadMetadata = async () => {
      try {
        const list = await api.getTopics();
        setTopicsList(list);
        const dups = await api.getDuplicateCandidates();
        setDuplicateCount(dups.length);
      } catch (err) {
        console.error('Failed to load initial metadata:', err);
      }
    };
    loadMetadata();
  }, []);

  // When topic changes, load topic summary for subtopics
  useEffect(() => {
    if (topic) {
      api.getTopicSummary(topic)
        .then((summary) => setAvailableSubtopics(summary.subtopics || []))
        .catch(() => setAvailableSubtopics([]));
    } else {
      setAvailableSubtopics([]);
      setSubtopic('');
    }
  }, [topic]);

  const fetchQuestions = async () => {
    setLoading(true);
    try {
      const data = await api.searchQuestions({
        query: query.trim() || undefined,
        topic: topic || undefined,
        subtopic: subtopic || undefined,
        tag: tagFilter.trim() || undefined,
        difficulty: difficulty || undefined,
        grade_min: gradeMin !== '' ? Number(gradeMin) : undefined,
        duplicate_status: activeTab === 'duplicates' ? 'POSSIBLE_DUPLICATE' : undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: 100,
      });
      setQuestions(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQuestions();
  }, [activeTab, topic, subtopic, tagFilter, difficulty, gradeMin, sortBy, sortOrder]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchQuestions();
  };

  const handleQuestionTagsSaved = (updated: HistoricalQuestion) => {
    setQuestions((prev) =>
      prev.map((item) => (item.id === updated.id ? { ...item, ...updated } : item))
    );
  };

  const handleResolveDuplicate = async (questionId: string, action: 'CONFIRM_DUPLICATE' | 'DISMISS_UNIQUE') => {
    setResolvingId(questionId);
    try {
      await api.resolveDuplicate(questionId, action);
      setQuestions((prev) => prev.filter((q) => q.id !== questionId));
      setDuplicateCount((prev) => Math.max(0, prev - 1));
      setSelectedDuplicateForReview(null);
    } catch (err) {
      console.error('Failed to resolve duplicate:', err);
    } finally {
      setResolvingId(null);
    }
  };

  const handleViewSlide = (q: HistoricalQuestion) => {
    setSelectedSlide({
      document_title: q.document_title,
      slide_number: q.slide_number,
      extracted_text: `${q.question_text}\n\n${(q.options || []).join('\n')}\n\nAnswer: ${q.answer}`,
      speaker_notes: q.explanation,
      slide_type: 'QUESTION',
    });
  };

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-slate-200/60 pb-5 gap-4">
        <div>
          <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
            Questions
          </h1>
          <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
            Verified, structured, and deduplicated questions across all historical QShala tournaments.
          </p>
        </div>

        {/* View Tabs */}
        <div className="flex items-center bg-slate-100 p-1 rounded-lg border border-slate-200/80">
          <button
            type="button"
            onClick={() => setActiveTab('all')}
            className={`px-3.5 py-1.5 rounded-md text-[13px] font-semibold transition-all cursor-pointer ${
              activeTab === 'all'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            All Questions
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('duplicates')}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-[13px] font-semibold transition-all cursor-pointer ${
              activeTab === 'duplicates'
                ? 'bg-amber-500 text-white shadow-sm'
                : 'text-amber-700 hover:text-amber-800'
            }`}
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>Possible Duplicates</span>
            {duplicateCount > 0 && (
              <span className={`px-1.5 py-0.2 rounded-full text-[11px] font-bold ${
                activeTab === 'duplicates' ? 'bg-white text-amber-600' : 'bg-amber-200 text-amber-900'
              }`}>
                {duplicateCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Search & Filters Bar */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm shadow-slate-100/50 space-y-3">
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by keywords, entities, concepts..."
              className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-4 text-[14px] font-normal text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-700 transition-colors cursor-pointer"
          >
            Search
          </button>
        </form>

        {/* Dynamic Filters & Sorting */}
        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-slate-100 text-[13px]">
          <div className="flex items-center gap-1.5 text-slate-500 font-medium">
            <Filter className="h-3.5 w-3.5" />
            <span>Filters:</span>
          </div>

          {/* Dynamic Topics Dropdown */}
          <select
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              setSubtopic('');
            }}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">All Topics ({topicsList.reduce((a, b) => a + b.count, 0)})</option>
            {topicsList.map((t) => (
              <option key={t.topic} value={t.topic}>
                {t.topic} ({t.count})
              </option>
            ))}
          </select>

          {/* Subtopic Filter (if available) */}
          {availableSubtopics.length > 0 && (
            <select
              value={subtopic}
              onChange={(e) => setSubtopic(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
            >
              <option value="">All Subtopics</option>
              {availableSubtopics.map((sub) => (
                <option key={sub} value={sub}>
                  {sub}
                </option>
              ))}
            </select>
          )}

          {/* Difficulty */}
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">All Difficulties</option>
            <option value="Easy">Easy</option>
            <option value="Medium">Medium</option>
            <option value="Hard">Hard</option>
          </select>

          {/* Grades */}
          <select
            value={gradeMin}
            onChange={(e) => setGradeMin(e.target.value === '' ? '' : Number(e.target.value))}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">Grade Filter</option>
            <option value="1">Grades 1+</option>
            <option value="3">Grades 3+</option>
            <option value="6">Grades 6+</option>
            <option value="9">Grades 9+</option>
          </select>

          {/* Tag Filter */}
          <div className="relative">
            <Tag className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by tag..."
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value.replace(/^#+/, ''))}
              className="rounded-md border border-slate-200 bg-white pl-8 pr-6 py-1.5 text-[13px] font-normal text-slate-700 placeholder-slate-400 focus:border-indigo-500 focus:outline-none w-[140px]"
            />
            {tagFilter && (
              <button
                type="button"
                onClick={() => setTagFilter('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-[12px] font-bold"
                title="Clear tag filter"
              >
                &times;
              </button>
            )}
          </div>

          {/* Sorting */}
          <div className="flex items-center gap-1.5 ml-auto">
            <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
            >
              <option value="created_at">Date Added</option>
              <option value="difficulty_score">Difficulty Score</option>
              <option value="curiosity_score">Curiosity Score</option>
              <option value="occurrence_count">Occurrences</option>
            </select>

            <button
              type="button"
              onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
              className="px-2 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 text-[12px] font-semibold cursor-pointer"
              title="Toggle sort direction"
            >
              {sortOrder.toUpperCase()}
            </button>
          </div>

          {(query || topic || subtopic || tagFilter || difficulty || gradeMin) && (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setTopic('');
                setSubtopic('');
                setTagFilter('');
                setDifficulty('');
                setGradeMin('');
              }}
              className="text-[13px] text-blue-600 hover:underline cursor-pointer font-medium"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Professional CMS Data Table */}
      <div className="rounded-xl border border-slate-200/80 bg-white shadow-sm shadow-slate-100/50 overflow-hidden">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-blue-600 mb-2" />
            <p className="text-[13px] text-slate-400 font-normal">Loading questions...</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px] border-collapse">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/60 font-semibold text-[12px] uppercase tracking-wider text-slate-600">
                  <th className="py-3 px-4 w-5/12">Question & Clues</th>
                  <th className="py-3 px-4">Topics</th>
                  <th className="py-3 px-4">Audience / Grade</th>
                  <th className="py-3 px-4">Difficulty & Depth</th>
                  <th className="py-3 px-4">Origin Presentation</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {questions.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-400">
                      {activeTab === 'duplicates'
                        ? 'No possible duplicates pending review!'
                        : 'No questions match your current search and filters.'}
                    </td>
                  </tr>
                ) : (
                  questions.map((q) => (
                    <tr key={q.id} className="hover:bg-slate-50/70 transition-colors group">
                      <td className="py-3.5 px-4">
                        {/* Duplicate Alert Banner */}
                        {q.duplicate_status === 'POSSIBLE_DUPLICATE' && (
                          <div className="mb-2 flex items-center justify-between rounded-md bg-amber-50 border border-amber-200 px-2.5 py-1.5 text-[11.5px] text-amber-800">
                            <span className="flex items-center gap-1.5 font-semibold">
                              <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                              Possible Duplicate ({Math.round((q.duplicate_similarity || 0.92) * 100)}% Match)
                            </span>
                            <button
                              type="button"
                              onClick={() => setSelectedDuplicateForReview(q)}
                              className="rounded bg-amber-600 px-2 py-0.5 font-semibold text-white hover:bg-amber-700 transition-colors text-[11px] cursor-pointer"
                            >
                              Review Match
                            </button>
                          </div>
                        )}

                        <div className="font-semibold text-[13.5px] text-slate-900 leading-snug">
                          {q.question_text}
                        </div>
                        <div className="mt-1 text-[12px] text-slate-600 font-normal">
                          Answer: <span className="font-semibold text-slate-800">{q.answer}</span>
                        </div>

                        {/* Multimodal Badges: Images, Audio, Video */}
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          {q.image_refs && q.image_refs.length > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-sky-50 border border-sky-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-sky-700">
                              <ImageIcon className="h-2.5 w-2.5" />
                              {q.image_refs.length} Images
                            </span>
                          )}
                          {q.visual_clues && (
                            <span className="inline-flex items-center gap-1 rounded bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-indigo-800 max-w-[200px] truncate" title={q.visual_clues}>
                              <span className="text-[10px] font-bold">OCR</span>
                              <span className="truncate">{q.visual_clues}</span>
                            </span>
                          )}
                          {q.audio_transcript && (
                            <span className="inline-flex items-center gap-1 rounded bg-teal-50 border border-teal-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-teal-800 max-w-[200px] truncate" title={q.audio_transcript}>
                              <Volume2 className="h-2.5 w-2.5 flex-shrink-0" />
                              <span className="truncate">{q.audio_transcript}</span>
                            </span>
                          )}
                          {q.video_transcript && (
                            <span className="inline-flex items-center gap-1 rounded bg-violet-50 border border-violet-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-violet-800 max-w-[200px] truncate" title={q.video_transcript}>
                              <Video className="h-2.5 w-2.5 flex-shrink-0" />
                              <span className="truncate">{q.video_transcript}</span>
                            </span>
                          )}
                          {q.source_slide_range && (
                            <span className="rounded bg-slate-100 border border-slate-200 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-600">
                              {q.source_slide_range}
                            </span>
                          )}
                          {q.question_hook && q.question_hook !== 'DIRECT_TRIVIA' && (
                            <span className="rounded bg-indigo-50 border border-indigo-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-indigo-700">
                              {q.question_hook.replace(/_/g, ' ')}
                            </span>
                          )}
                          {q.tags && q.tags.map((tag) => (
                            <button
                              key={tag}
                              type="button"
                              onClick={() => setTagFilter(tagFilter.toLowerCase() === tag.toLowerCase() ? '' : tag)}
                              className={`rounded px-1.5 py-0.5 text-[10.5px] font-medium transition-colors cursor-pointer ${
                                tagFilter.toLowerCase() === tag.toLowerCase()
                                  ? 'bg-indigo-600 text-white font-semibold'
                                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                              }`}
                              title={`Filter by #${tag}`}
                            >
                              #{tag}
                            </button>
                          ))}
                          <button
                            type="button"
                            onClick={() => setSelectedQuestionForTags(q)}
                            className="inline-flex items-center gap-0.5 rounded border border-dashed border-slate-300 hover:border-indigo-400 bg-white hover:bg-indigo-50/50 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-500 hover:text-indigo-600 transition-colors cursor-pointer"
                            title="Add or edit tags for this question"
                          >
                            <Plus className="h-2.5 w-2.5" />
                            <span>Tag</span>
                          </button>
                          {q.occurrence_count && q.occurrence_count > 1 && (
                            <span className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-emerald-700 flex items-center gap-1">
                              <Layers className="h-2.5 w-2.5" />
                              Appears in {q.occurrence_count} decks
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Topics */}
                      <td className="py-3.5 px-4 align-top">
                        <div className="flex flex-col gap-1">
                          <span className="rounded-md bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] font-semibold text-amber-800 w-fit">
                            {q.topic}
                          </span>
                          {q.subtopic && (
                            <span className="text-[11px] text-slate-500 font-medium">
                              {q.subtopic}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Audience */}
                      <td className="py-3.5 px-4 text-slate-600 align-top">
                        <div className="font-semibold text-[13px] text-slate-800">
                          Grades {q.grade_min}–{q.grade_max}
                        </div>
                        <div className="text-[11px] text-slate-400 font-normal">
                          Ages {q.grade_min + 5}–{q.grade_max + 6}
                        </div>
                      </td>

                      {/* Difficulty & Depth */}
                      <td className="py-3.5 px-4 align-top">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${
                              q.difficulty === 'Easy'
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : q.difficulty === 'Hard'
                                ? 'bg-purple-50 text-purple-700 border border-purple-200'
                                : 'bg-blue-50 text-blue-700 border border-blue-200'
                            }`}
                          >
                            {q.difficulty}
                          </span>
                          {q.difficulty_score !== undefined && (
                            <span className="text-[11px] font-mono text-slate-400">
                              {q.difficulty_score.toFixed(2)}
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-500 font-normal mt-1">
                          {q.cognitive_level || 'Recall'}
                        </div>
                      </td>

                      {/* Source */}
                      <td className="py-3.5 px-4 text-slate-500 text-[12px] align-top">
                        <div className="truncate max-w-[150px] font-medium text-slate-700">
                          {q.document_title || 'Archive'}
                        </div>
                        <div className="text-[11px] text-slate-400">
                          Slide {q.slide_number || 1}
                        </div>
                      </td>

                      <td className="py-3.5 px-4 text-right align-top">
                        <div className="flex items-center justify-end gap-3">
                          {q.duplicate_status === 'POSSIBLE_DUPLICATE' ? (
                            <button
                              onClick={() => setSelectedDuplicateForReview(q)}
                              className="inline-flex items-center gap-1 rounded bg-amber-600 px-2 py-1 text-[11px] font-bold text-white hover:bg-amber-700 cursor-pointer"
                            >
                              <span>Resolve</span>
                            </button>
                          ) : (
                            <>
                              <button
                                onClick={() => setSelectedQuestionForTags(q)}
                                className="inline-flex items-center gap-1 text-[12px] font-semibold text-indigo-600 hover:text-indigo-700 cursor-pointer"
                                title="Manage tags and categories"
                              >
                                <Tag className="h-3 w-3" />
                                <span>Tags</span>
                              </button>
                              <button
                                onClick={() => handleViewSlide(q)}
                                className="inline-flex items-center gap-1 text-[12px] font-semibold text-blue-600 hover:text-blue-700 cursor-pointer"
                              >
                                <span>View slide</span>
                                <ExternalLink className="h-3 w-3" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Duplicate Review & Resolution Modal */}
      {selectedDuplicateForReview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="w-full max-w-3xl rounded-xl bg-white shadow-xl border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 bg-amber-50/50">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-amber-600" />
                <h3 className="text-[16px] font-bold text-slate-900">
                  Duplicate Candidate Review ({Math.round((selectedDuplicateForReview.duplicate_similarity || 0.92) * 100)}% Match)
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDuplicateForReview(null)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-md"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6 space-y-6 overflow-y-auto">
              <p className="text-[13px] text-slate-600 leading-relaxed">
                This newly ingested question has a cosine similarity score of{' '}
                <span className="font-bold text-amber-700">
                  {(selectedDuplicateForReview.duplicate_similarity || 0.92).toFixed(3)}
                </span>{' '}
                against an existing question in your Knowledge Base. Review both versions below:
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Candidate (New) Question */}
                <div className="rounded-lg border border-amber-200 bg-amber-50/20 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-amber-100 pb-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-amber-800">
                      Newly Ingested Candidate
                    </span>
                    <span className="text-[11px] text-slate-500 font-medium">
                      {selectedDuplicateForReview.document_title || 'Current Deck'}
                    </span>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Question</span>
                    <p className="text-[13.5px] font-medium text-slate-900 mt-0.5">
                      {selectedDuplicateForReview.question_text}
                    </p>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Answer</span>
                    <p className="text-[13.5px] font-bold text-slate-800 mt-0.5">
                      {selectedDuplicateForReview.answer}
                    </p>
                  </div>

                  {selectedDuplicateForReview.audio_transcript && (
                    <div className="rounded bg-white/80 p-2 border border-amber-100 text-[11.5px]">
                      <span className="font-bold text-slate-700">Audio transcript:</span>{' '}
                      {selectedDuplicateForReview.audio_transcript}
                    </div>
                  )}

                  {selectedDuplicateForReview.video_transcript && (
                    <div className="rounded bg-white/80 p-2 border border-amber-100 text-[11.5px]">
                      <span className="font-bold text-slate-700">Video transcript:</span>{' '}
                      {selectedDuplicateForReview.video_transcript}
                    </div>
                  )}
                </div>

                {/* Matched Original Question */}
                <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-slate-600">
                      Existing Knowledge Base Match
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      ID: {selectedDuplicateForReview.duplicate_of_id?.slice(0, 8) || 'Match'}
                    </span>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Question</span>
                    <p className="text-[13.5px] font-medium text-slate-900 mt-0.5">
                      {selectedDuplicateForReview.duplicate_of_text || selectedDuplicateForReview.question_text}
                    </p>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Answer</span>
                    <p className="text-[13.5px] font-bold text-slate-800 mt-0.5">
                      {selectedDuplicateForReview.duplicate_of_answer || selectedDuplicateForReview.answer}
                    </p>
                  </div>

                  <div className="rounded bg-white p-2 border border-slate-200 text-[11.5px] text-slate-500">
                    Already appears in repository across historical tournaments.
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50 px-6 py-4">
              <button
                type="button"
                onClick={() => setSelectedDuplicateForReview(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-[13px] font-medium text-slate-700 hover:bg-white transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={resolvingId === selectedDuplicateForReview.id}
                onClick={() => handleResolveDuplicate(selectedDuplicateForReview.id, 'DISMISS_UNIQUE')}
                className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-[13px] font-semibold text-emerald-800 hover:bg-emerald-100 transition-colors cursor-pointer flex items-center gap-1.5"
              >
                <CheckCircle className="h-4 w-4 text-emerald-600" />
                <span>Dismiss as Unique</span>
              </button>
              <button
                type="button"
                disabled={resolvingId === selectedDuplicateForReview.id}
                onClick={() => handleResolveDuplicate(selectedDuplicateForReview.id, 'CONFIRM_DUPLICATE')}
                className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-700 transition-colors cursor-pointer flex items-center gap-1.5"
              >
                <Copy className="h-4 w-4" />
                <span>Confirm Duplicate (Link Provenance)</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedSlide && (
        <SlideViewerModal
          isOpen={!!selectedSlide}
          onClose={() => setSelectedSlide(null)}
          slide={selectedSlide}
        />
      )}

      {selectedQuestionForTags && (
        <TagManagerModal
          isOpen={!!selectedQuestionForTags}
          onClose={() => setSelectedQuestionForTags(null)}
          question={selectedQuestionForTags}
          onSaved={handleQuestionTagsSaved}
          availableTopics={topicsList.map((t) => t.topic)}
        />
      )}
    </div>
  );
}

export default function KnowledgeBasePage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-slate-400">Loading...</div>}>
      <KnowledgeBaseContent />
    </Suspense>
  );
}
