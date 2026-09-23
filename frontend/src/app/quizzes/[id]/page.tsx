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
  Presentation,
  Play,
  ChevronLeft,
  ChevronRight,
  X,
  Sparkles,
  Tag,
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

  // Live Slide Deck Presentation Mode
  const [isPresenting, setIsPresenting] = useState(false);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);

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

  const approvedQuestions = quiz.questions.filter((q) => q.is_approved);
  const totalSlides = approvedQuestions.length * 2; // Slide 1 = Question, Slide 2 = Answer

  // Slide Deck navigation
  const currentQuestionIdx = Math.floor(currentSlideIndex / 2);
  const isAnswerSlide = currentSlideIndex % 2 === 1;
  const currentQuestion = approvedQuestions[currentQuestionIdx];

  const nextSlide = () => {
    if (currentSlideIndex < totalSlides - 1) {
      setCurrentSlideIndex((prev) => prev + 1);
    }
  };

  const prevSlide = () => {
    if (currentSlideIndex > 0) {
      setCurrentSlideIndex((prev) => prev - 1);
    }
  };

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-4xl mx-auto space-y-6 pb-20">
      {/* Top Breadcrumb & Export Actions */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200/60 pb-4">
        <Link
          href="/quizzes"
          className="flex items-center gap-1.5 text-[13px] font-medium text-slate-500 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>Back to Generated Quizzes</span>
        </Link>

        {/* Action & Export Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {approvedQuestions.length > 0 && (
            <button
              onClick={() => {
                setCurrentSlideIndex(0);
                setIsPresenting(true);
              }}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-1.5 text-[13px] font-semibold text-white hover:bg-emerald-700 transition-colors shadow-sm cursor-pointer"
            >
              <Play className="h-3.5 w-3.5 fill-current" />
              <span>Present Slide Deck</span>
            </button>
          )}

          <a
            href={api.exportQuizUrl(quiz.id, 'pptx')}
            download
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-1.5 text-[13px] font-semibold text-white hover:bg-blue-700 transition-colors shadow-sm"
          >
            <Presentation className="h-3.5 w-3.5" />
            <span>Download PPTX</span>
          </a>

          <a
            href={api.exportQuizUrl(quiz.id, 'json')}
            download
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
          >
            <FileJson className="h-3.5 w-3.5 text-slate-500" />
            <span>JSON</span>
          </a>

          <a
            href={api.exportQuizUrl(quiz.id, 'csv')}
            download
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
          >
            <FileSpreadsheet className="h-3.5 w-3.5 text-slate-500" />
            <span>CSV</span>
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
            {approvedQuestions.length} / {quiz.questions.length} Approved
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[13px] text-slate-500 font-normal">
          <span>
            {quiz.grade_min && quiz.grade_max
              ? `Grades ${quiz.grade_min}–${quiz.grade_max}`
              : (quiz.audience_type || 'General').replace('_', ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
          </span>
          <span className="text-slate-300">•</span>
          <span>{quiz.question_count} Questions (Slide Pairs)</span>
          <span className="text-slate-300">•</span>
          <span>{quiz.difficulty} Difficulty</span>
          <span className="text-slate-300">•</span>
          <span className="text-emerald-600 font-medium">Question → Next Slide Answer Format</span>
        </div>

        {quiz.tags && quiz.tags.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-100 text-[12px]">
            <div className="flex flex-wrap items-center gap-1">
              {quiz.tags.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                  <Tag className="h-3 w-3 text-slate-400" />
                  <span>#{t}</span>
                </span>
              ))}
            </div>
          </div>
        )}
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

      {/* Slide Viewer Modal */}
      <SlideViewerModal
        isOpen={Boolean(selectedSlide)}
        onClose={() => setSelectedSlide(null)}
        slide={selectedSlide}
      />

      {/* Live Slide Deck Presentation Modal */}
      {isPresenting && currentQuestion && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 sm:p-8">
          <div className="relative w-full max-w-4xl rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden flex flex-col min-h-[480px]">
            {/* Top Stage Bar */}
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 bg-slate-50/70">
              <div className="flex items-center gap-3">
                <span className="text-[12px] font-bold uppercase tracking-wider text-slate-500">
                  Slide {currentSlideIndex + 1} of {totalSlides}
                </span>
                <span className="text-slate-300">•</span>
                <span className={`text-[12px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded ${
                  isAnswerSlide ? 'bg-emerald-100 text-emerald-800' : 'bg-blue-100 text-blue-800'
                }`}>
                  {isAnswerSlide ? `Answer ${currentQuestionIdx + 1}` : `Question ${currentQuestionIdx + 1}`}
                </span>
                <span className="text-slate-300">•</span>
                <span className="text-[12px] font-medium text-slate-500">{currentQuestion.difficulty}</span>
              </div>

              <button
                onClick={() => setIsPresenting(false)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 transition-colors cursor-pointer"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Slide Stage Body */}
            <div className="flex-1 p-8 sm:p-12 flex flex-col justify-center">
              {!isAnswerSlide ? (
                /* Question Slide Content */
                <div className="space-y-6">
                  <div className="text-[13px] font-bold tracking-wider text-blue-600 uppercase flex items-center gap-2">
                    <Sparkles className="h-4 w-4" />
                    <span>QShala Question Slide</span>
                  </div>
                  <h2 className="text-[24px] sm:text-[32px] font-bold text-slate-900 leading-snug">
                    {currentQuestion.question_text}
                  </h2>
                  <p className="text-[14px] text-slate-500 italic">
                    Think carefully... click Next Slide to reveal the answer!
                  </p>
                </div>
              ) : (
                /* Answer Slide Content */
                <div className="space-y-6">
                  <div className="text-[13px] font-bold tracking-wider text-emerald-600 uppercase flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    <span>Answer & Educational Explanation</span>
                  </div>

                  <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-5">
                    <span className="text-[12px] font-bold uppercase tracking-wider text-emerald-800 block mb-1">
                      Correct Answer:
                    </span>
                    <h2 className="text-[26px] sm:text-[30px] font-bold text-emerald-950 leading-tight">
                      {currentQuestion.answer}
                    </h2>
                  </div>

                  {currentQuestion.explanation && (
                    <div className="rounded-xl border border-slate-100 bg-slate-50 p-5 space-y-1.5">
                      <span className="text-[12px] font-bold uppercase tracking-wider text-slate-500 block">
                        The Story Behind It:
                      </span>
                      <p className="text-[15px] sm:text-[16px] text-slate-700 leading-relaxed font-normal">
                        {currentQuestion.explanation}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Slide Controls Bottom Bar */}
            <div className="flex items-center justify-between border-t border-slate-100 px-6 py-4 bg-slate-50/70">
              <button
                onClick={prevSlide}
                disabled={currentSlideIndex === 0}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronLeft className="h-4 w-4" />
                <span>Previous Slide</span>
              </button>

              <span className="text-[12px] text-slate-500 font-medium">
                {isAnswerSlide ? 'Answer Revealed' : 'Question Prompt'}
              </span>

              <button
                onClick={nextSlide}
                disabled={currentSlideIndex === totalSlides - 1}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <span>{!isAnswerSlide ? 'Reveal Answer' : 'Next Question'}</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
