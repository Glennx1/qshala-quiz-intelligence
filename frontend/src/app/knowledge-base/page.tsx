'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Search,
  Filter,
  ExternalLink,
  Loader2,
  Bookmark,
} from 'lucide-react';
import { api } from '../../lib/api';
import { HistoricalQuestion } from '../../lib/types';
import SlideViewerModal from '../../components/SlideViewerModal';

function KnowledgeBaseContent() {
  const searchParams = useSearchParams();
  const initialTopic = searchParams.get('topic') || '';

  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState(initialTopic);
  const [difficulty, setDifficulty] = useState('');
  const [gradeMin, setGradeMin] = useState<number | ''>('');
  const [questions, setQuestions] = useState<HistoricalQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);

  const fetchQuestions = async () => {
    setLoading(true);
    try {
      const data = await api.searchQuestions({
        query: query.trim() || undefined,
        topic: topic || undefined,
        difficulty: difficulty || undefined,
        grade_min: gradeMin !== '' ? Number(gradeMin) : undefined,
        limit: 50,
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
  }, [topic, difficulty, gradeMin]);

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
            Knowledge Base
          </h1>
          <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
            Search questions, topics, and slide origins across the QShala archives.
          </p>
        </div>

        <span className="rounded-md bg-slate-100 px-3 py-1 text-[12px] font-semibold text-slate-700">
          {questions.length} Questions
        </span>
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
              placeholder="Search questions, topics, documents..."
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

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-slate-100 text-[13px]">
          <div className="flex items-center gap-1.5 text-slate-500 font-medium">
            <Filter className="h-3.5 w-3.5" />
            <span>Filters:</span>
          </div>

          <select
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">All Topics</option>
            <option value="Australian History">Australian History</option>
            <option value="World Geography">World Geography</option>
            <option value="Science & Nature">Science & Nature</option>
          </select>

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

          <select
            value={gradeMin}
            onChange={(e) => setGradeMin(e.target.value === '' ? '' : Number(e.target.value))}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">Grade Filter</option>
            <option value="3">Grade 3+</option>
            <option value="5">Grade 5+</option>
          </select>

          {(query || topic || difficulty || gradeMin) && (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setTopic('');
                setDifficulty('');
                setGradeMin('');
              }}
              className="text-[13px] text-blue-600 hover:underline cursor-pointer ml-auto font-medium"
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
            <p className="text-[13px] text-slate-400 font-normal">Loading knowledge base...</p>
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
                  <th className="py-3 px-4">Source</th>
                  <th className="py-3 px-4">Vault Status</th>
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
                          <span key={tag} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-normal text-slate-600">
                            #{tag}
                          </span>
                        ))}
                        {q.occurrence_count && q.occurrence_count > 1 && (
                          <span className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-emerald-700">
                            Appears in {q.occurrence_count} decks
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Multi-Topic Badges */}
                    <td className="py-3.5 px-4 align-top">
                      <div className="flex flex-wrap gap-1 max-w-[170px]">
                        {(q.topics && q.topics.length > 0 ? q.topics : [q.topic]).map((t) => {
                          const isHistory = t.includes('History');
                          const isScience = t.includes('Science') || t.includes('Nature');
                          const isPolitics = t.includes('Politics') || t.includes('Governance');
                          const isGeo = t.includes('Geography');
                          const colorCls = isHistory
                            ? 'bg-amber-50 text-amber-700 border-amber-200/80'
                            : isScience
                            ? 'bg-blue-50 text-blue-700 border-blue-200/80'
                            : isPolitics
                            ? 'bg-purple-50 text-purple-700 border-purple-200/80'
                            : isGeo
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200/80'
                            : 'bg-slate-100 text-slate-700 border-slate-200/80';
                          return (
                            <span key={t} className={`rounded-md border px-2 py-0.5 text-[11px] font-medium ${colorCls}`}>
                              {t}
                            </span>
                          );
                        })}
                      </div>
                    </td>

                    {/* Grade Range */}
                    <td className="py-3.5 px-4 text-slate-600 align-top">
                      <div className="font-semibold text-[13px] text-slate-800">
                        Grades {q.grade_min}–{q.grade_max}
                      </div>
                      <div className="text-[11px] text-slate-400 font-normal">
                        Ages {q.grade_min + 5}–{q.grade_max + 6}
                      </div>
                    </td>

                    {/* Difficulty & Cognitive Level */}
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
                      <div className="truncate max-w-[130px] font-medium text-slate-700">
                        {q.document_title || 'Archive'}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        Slide {q.slide_number || 1}
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4 align-top">
                      <div className="flex items-center gap-1.5 text-[12px] text-emerald-700 font-medium bg-emerald-50 px-2 py-0.5 rounded-full w-fit border border-emerald-100">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        <span>Unique</span>
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

                {questions.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-[13px] text-slate-400 font-normal">
                      No matching questions found in knowledge base.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <SlideViewerModal
        isOpen={Boolean(selectedSlide)}
        onClose={() => setSelectedSlide(null)}
        slide={selectedSlide}
      />
    </div>
  );
}

export default function KnowledgeBasePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
        </div>
      }
    >
      <KnowledgeBaseContent />
    </Suspense>
  );
}
