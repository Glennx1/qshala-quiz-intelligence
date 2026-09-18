'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  FileJson,
  FileSpreadsheet,
  Printer,
  Loader2,
} from 'lucide-react';
import { api } from '../../../lib/api';
import { Quiz, GeneratedQuestion, RetrievalSource } from '../../../lib/types';
import QuestionCard from '../../../components/QuestionCard';
import SlideViewerModal from '../../../components/SlideViewerModal';

export default function QuizReviewStudioPage() {
  const params = useParams();
  const quizId = params.id as string;

  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);

  const fetchQuiz = async () => {
    try {
      const data = await api.getQuiz(quizId);
      setQuiz(data);
    } catch (err) {
      console.error('Error fetching quiz:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (quizId) fetchQuiz();
  }, [quizId]);

  const handleUpdateQuestion = async (qId: string, updated: Partial<GeneratedQuestion>) => {
    try {
      const saved = await api.updateQuestion(qId, updated);
      if (quiz) {
        setQuiz({
          ...quiz,
          questions: quiz.questions.map((q) => (q.id === qId ? { ...q, ...saved } : q)),
        });
      }
    } catch (e) {
      console.error(e);
      alert('Failed to update question');
    }
  };

  const handleQuestionAction = async (
    qId: string,
    action: 'regenerate' | 'make_easier' | 'make_harder' | 'generate_similar'
  ) => {
    try {
      const refreshed = await api.executeQuestionAction(qId, action);
      if (quiz) {
        setQuiz({
          ...quiz,
          questions: quiz.questions.map((q) => (q.id === qId ? refreshed : q)),
        });
      }
    } catch (e: any) {
      console.error(e);
      alert(e.message || 'Action failed');
    }
  };

  const handleDeleteQuestion = async (qId: string) => {
    if (!confirm('Are you sure you want to remove this question from the quiz?')) return;
    try {
      await api.deleteQuestion(qId);
      if (quiz) {
        setQuiz({
          ...quiz,
          questions: quiz.questions.filter((q) => q.id !== qId),
        });
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleViewSource = (src: RetrievalSource) => {
    setSelectedSlide({
      document_title: src.document_title,
      slide_number: src.slide_number,
      quote: src.source_quote,
      extracted_text: src.source_quote,
      speaker_notes: src.rationale,
      slide_type: 'HISTORICAL_SOURCE',
    });
  };

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
      </div>
    );
  }

  if (!quiz) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center">
        <p className="text-slate-600">Quiz not found.</p>
        <Link href="/quizzes" className="mt-2 text-xs font-semibold text-blue-600 underline">
          Back to Library
        </Link>
      </div>
    );
  }

  const approvedCount = quiz.questions.filter((q) => q.is_approved).length;

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-4xl mx-auto space-y-6 pb-20">
      {/* Top Breadcrumb & Export Actions */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200/60 pb-4">
        <Link
          href="/quizzes"
          className="flex items-center gap-1.5 text-[13px] font-medium text-slate-500 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>Back to Quiz Library</span>
        </Link>

        {/* Export Buttons */}
        <div className="flex items-center gap-2">
          <a
            href={api.exportQuizUrl(quiz.id, 'json')}
            download
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
          >
            <FileJson className="h-3.5 w-3.5 text-slate-500" />
            <span>Export JSON</span>
          </a>

          <a
            href={api.exportQuizUrl(quiz.id, 'csv')}
            download
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
          >
            <FileSpreadsheet className="h-3.5 w-3.5 text-slate-500" />
            <span>Export CSV</span>
          </a>

          <button
            onClick={() => window.print()}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm cursor-pointer"
          >
            <Printer className="h-3.5 w-3.5 text-slate-500" />
            <span>Print</span>
          </button>
        </div>
      </div>

      {/* Clean Quiz Header Card */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-6 shadow-sm shadow-slate-100/50 space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-[24px] sm:text-[28px] font-bold tracking-tight text-slate-900">
            {quiz.title}
          </h1>
          <span className="text-[12px] font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-md">
            {approvedCount} / {quiz.questions.length} Approved
          </span>
        </div>

        <p className="text-[13px] text-slate-500 font-normal leading-relaxed">
          {quiz.grade_min && quiz.grade_max
            ? `Grades ${quiz.grade_min}–${quiz.grade_max}`
            : ((quiz.audience_type || 'General').replace('_', ' ').replace(/\b\w/g, (l) => l.toUpperCase()))} · {quiz.question_count} Questions · {quiz.difficulty} difficulty · Grounded in QShala Knowledge Base
        </p>
      </div>

      {/* Questions Stream */}
      <div className="space-y-4">
        {quiz.questions.map((q) => (
          <QuestionCard
            key={q.id}
            question={q}
            onUpdate={handleUpdateQuestion}
            onAction={handleQuestionAction}
            onDelete={handleDeleteQuestion}
            onViewSource={handleViewSource}
          />
        ))}
      </div>

      <SlideViewerModal
        isOpen={Boolean(selectedSlide)}
        onClose={() => setSelectedSlide(null)}
        slide={selectedSlide}
      />
    </div>
  );
}
