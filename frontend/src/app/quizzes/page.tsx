'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Plus,
  FileJson,
  FileSpreadsheet,
  Presentation,
  ArrowRight,
  Loader2,
} from 'lucide-react';
import { api } from '../../lib/api';
import { Quiz } from '../../lib/types';

export default function QuizzesLibraryPage() {
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchQuizzes = async () => {
    try {
      const data = await api.listQuizzes();
      setQuizzes(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQuizzes();
  }, []);

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200/60 pb-5">
        <div>
          <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
            Quiz Library
          </h1>
          <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
            Browse, review, edit, and export generated quizzes.
          </p>
        </div>

        <Link
          href="/generate"
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[13px] sm:text-[14px] font-semibold text-white hover:bg-blue-700 transition-colors shadow-sm cursor-pointer"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>New Quiz</span>
        </Link>
      </div>

      {/* Clean Table List of Quizzes */}
      <div className="rounded-xl border border-slate-200/80 bg-white shadow-sm shadow-slate-100/50 overflow-hidden">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-blue-600 mb-2" />
            <p className="text-[13px] text-slate-400 font-normal">Loading quiz library...</p>
          </div>
        ) : (
          <table className="w-full text-left text-[13px] border-collapse">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60 font-semibold text-[12px] uppercase tracking-wider text-slate-600">
                <th className="py-3 px-4">Quiz Title</th>
                <th className="py-3 px-4">Topic</th>
                <th className="py-3 px-4">Grades</th>
                <th className="py-3 px-4">Questions</th>
                <th className="py-3 px-4">Difficulty</th>
                <th className="py-3 px-4">Created</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {quizzes.map((quiz) => (
                <tr key={quiz.id} className="hover:bg-slate-50/70 transition-colors group">
                  <td className="py-3.5 px-4 font-semibold text-[14px] text-slate-900">
                    <Link
                      href={`/quizzes/${quiz.id}`}
                      className="hover:text-blue-600 transition-colors flex items-center gap-2"
                    >
                      <span>{quiz.title}</span>
                    </Link>
                  </td>
                  <td className="py-3.5 px-4 text-slate-600">{quiz.topic}</td>
                  <td className="py-3.5 px-4 text-slate-600">
                    Grades {quiz.grade_min}–{quiz.grade_max}
                  </td>
                  <td className="py-3.5 px-4 text-slate-600 font-medium">
                    {quiz.question_count} Qs
                  </td>
                  <td className="py-3.5 px-4 text-slate-600">{quiz.difficulty}</td>
                  <td className="py-3.5 px-4 text-slate-400 text-[12px] font-normal">
                    {quiz.created_at ? new Date(quiz.created_at).toLocaleDateString() : 'Recent'}
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <div className="inline-flex items-center gap-2 opacity-90 group-hover:opacity-100 transition-opacity">
                      <a
                        href={api.exportQuizUrl(quiz.id, 'json')}
                        download
                        className="rounded p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
                        title="Download JSON"
                      >
                        <FileJson className="h-3.5 w-3.5" />
                      </a>
                      <a
                        href={api.exportQuizUrl(quiz.id, 'csv')}
                        download
                        className="rounded p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
                        title="Download CSV"
                      >
                        <FileSpreadsheet className="h-3.5 w-3.5" />
                      </a>
                      <a
                        href={api.exportQuizUrl(quiz.id, 'pptx')}
                        download
                        className="rounded p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                        title="Download QShala Master PPTX"
                      >
                        <Presentation className="h-3.5 w-3.5" />
                      </a>
                      <Link
                        href={`/quizzes/${quiz.id}`}
                        className="inline-flex items-center gap-1 font-semibold text-[12px] text-blue-600 hover:text-blue-700 pl-2"
                      >
                        <span>Open</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}

              {quizzes.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[13px] text-slate-400 font-normal">
                    No quizzes generated yet. Click "New Quiz" above to create one.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
