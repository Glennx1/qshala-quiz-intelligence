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
} from 'lucide-react';
import { api } from '../../lib/api';
import { HistoricalQuestion, TopicItem } from '../../lib/types';
import SlideViewerModal from '../../components/SlideViewerModal';

function KnowledgeBaseContent() {
  const searchParams = useSearchParams();
  const initialTopic = searchParams.get('topic') || '';

  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState(initialTopic);
  const [subtopic, setSubtopic] = useState('');
  const [difficulty, setDifficulty] = useState('');
  const [gradeMin, setGradeMin] = useState<number | ''>('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');

  const [topicsList, setTopicsList] = useState<TopicItem[]>([]);
  const [availableSubtopics, setAvailableSubtopics] = useState<string[]>([]);
  const [questions, setQuestions] = useState<HistoricalQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);

  // Fetch topics list on mount
  useEffect(() => {
    const loadTopics = async () => {
      try {
        const list = await api.getTopics();
        setTopicsList(list);
      } catch (err) {
        console.error('Failed to load topics:', err);
      }
    };
    loadTopics();
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
        difficulty: difficulty || undefined,
        grade_min: gradeMin !== '' ? Number(gradeMin) : undefined,
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
  }, [topic, subtopic, difficulty, gradeMin, sortBy, sortOrder]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchQuestions();
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
      <div className="flex items-center justify-between border-b border-slate-200/60 pb-5">
        <div>
          <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
            Question Vault
          </h1>
          <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
            Verified, structured, and deduplicated questions across all historical QShala tournaments.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className="rounded-md bg-blue-50 border border-blue-100 px-3 py-1 text-[12px] font-semibold text-blue-700">
            {questions.length} Questions in View
          </span>
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

          {(query || topic || subtopic || difficulty || gradeMin) && (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setTopic('');
                setSubtopic('');
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
            <p className="text-[13px] text-slate-400 font-normal">Loading question vault...</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px] border-collapse">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/60 font-semibold text-[12px] uppercase tracking-wider text-slate-600">
                  <th className="py-3 px-4 w-5/12">Question & Concepts</th>
                  <th className="py-3 px-4">Topics</th>
                  <th className="py-3 px-4">Audience / Grade</th>
                  <th className="py-3 px-4">Difficulty & Depth</th>
                  <th className="py-3 px-4">Origin Presentation</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {questions.map((q) => (
                  <tr key={q.id} className="hover:bg-slate-50/70 transition-colors group">
                    <td className="py-3.5 px-4">
                      <div className="font-semibold text-[13.5px] text-slate-900 leading-snug">
                        {q.question_text}
                      </div>
                      <div className="mt-1 text-[12px] text-slate-600 font-normal">
                        Answer: <span className="font-semibold text-slate-800">{q.answer}</span>
                      </div>

                      {/* Entities and Question Hooks */}
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        {q.question_hook && q.question_hook !== 'DIRECT_TRIVIA' && (
                          <span className="rounded bg-indigo-50 border border-indigo-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-indigo-700">
                            {q.question_hook.replace(/_/g, ' ')}
                          </span>
                        )}
                        {q.tags && q.tags.slice(0, 4).map((tag) => (
                          <span
                            key={tag}
                            className="rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-600"
                          >
                            #{tag}
                          </span>
                        ))}
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
                      <button
                        onClick={() => handleViewSlide(q)}
                        className="inline-flex items-center gap-1 text-[12px] font-semibold text-blue-600 hover:text-blue-700 cursor-pointer"
                      >
                        <span>View slide</span>
                        <ExternalLink className="h-3 w-3" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedSlide && (
        <SlideViewerModal
          isOpen={!!selectedSlide}
          onClose={() => setSelectedSlide(null)}
          slide={selectedSlide}
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
