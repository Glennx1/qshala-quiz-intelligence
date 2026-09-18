'use client';

import { useState } from 'react';
import {
  Check,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Trash2,
  Edit2,
  Bookmark,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from 'lucide-react';
import { GeneratedQuestion, RetrievalSource } from '../lib/types';

interface Props {
  question: GeneratedQuestion;
  onUpdate: (id: string, updated: Partial<GeneratedQuestion>) => Promise<void>;
  onAction: (id: string, action: 'regenerate' | 'make_easier' | 'make_harder' | 'generate_similar') => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onViewSource: (src: RetrievalSource) => void;
}

export default function QuestionCard({
  question,
  onUpdate,
  onAction,
  onDelete,
  onViewSource,
}: Props) {
  const [isEditing, setIsEditing] = useState(false);
  const [qText, setQText] = useState(question.question_text);
  const [options, setOptions] = useState<string[]>(question.options || []);
  const [answer, setAnswer] = useState(question.answer);
  const [explanation, setExplanation] = useState(question.explanation || '');
  const [showSource, setShowSource] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const handleSave = async () => {
    await onUpdate(question.id, {
      question_text: qText,
      options,
      answer,
      explanation,
    });
    setIsEditing(false);
  };

  const handleAction = async (action: 'regenerate' | 'make_easier' | 'make_harder' | 'generate_similar') => {
    setActionLoading(action);
    try {
      await onAction(question.id, action);
    } finally {
      setActionLoading(null);
    }
  };

  const handleOptionChange = (idx: number, val: string) => {
    const next = [...options];
    next[idx] = val;
    setOptions(next);
  };

  const primarySource = question.retrieval_sources?.[0];

  return (
    <div
      className={`rounded-xl border bg-white p-6 transition-all shadow-sm shadow-slate-100/50 ${
        question.is_approved ? 'border-slate-200/80' : 'border-slate-200 opacity-60 bg-slate-50/50'
      }`}
    >
      {/* Top Meta Bar */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-3 mb-4">
        <div className="flex items-center gap-3">
          <span className="text-[14px] font-bold text-slate-900">
            {question.order_index}.
          </span>
          <span className="text-[12px] font-medium text-slate-500">
            {question.difficulty}
          </span>
          <span className="text-slate-300">•</span>
          <span className="text-[12px] text-slate-500 font-medium">
            Grades {question.grade_min}–{question.grade_max}
          </span>
        </div>

        {/* Status Indicator & Approval */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-[12px] text-slate-500">
            <span
              className={`h-2 w-2 rounded-full ${
                question.validation_status === 'PASSED'
                  ? 'bg-emerald-500'
                  : question.validation_status === 'WARNING'
                  ? 'bg-amber-500'
                  : 'bg-red-500'
              }`}
            />
            <span className="font-medium text-[12px] text-slate-600">
              {question.validation_status === 'PASSED' ? 'Validated' : 'Needs Review'}
            </span>
          </div>

          <button
            onClick={() => onUpdate(question.id, { is_approved: !question.is_approved })}
            className={`rounded-md px-2.5 py-1 text-[12px] font-semibold transition-colors ${
              question.is_approved
                ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {question.is_approved ? 'Approved' : 'Rejected'}
          </button>
        </div>
      </div>

      {/* Question Content */}
      <div className="space-y-4">
        {isEditing ? (
          <div>
            <textarea
              value={qText}
              onChange={(e) => setQText(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-slate-200 bg-white p-3 text-[14px] text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
        ) : (
          <h3 className="text-[15px] sm:text-[16px] font-semibold text-slate-900 leading-relaxed">
            {question.question_text}
          </h3>
        )}

        {/* Options List */}
        {options.length > 0 && (
          <div className="space-y-2">
            {options.map((opt, idx) => {
              const isCorrect =
                opt.trim().toLowerCase() === question.answer.trim().toLowerCase() ||
                question.answer.includes(opt.slice(0, 2));

              return (
                <div
                  key={idx}
                  className={`flex items-center justify-between rounded-lg border px-3.5 py-2.5 text-[13.5px] transition-all ${
                    isCorrect
                      ? 'border-emerald-200 bg-emerald-50/70 text-emerald-900 font-medium'
                      : 'border-slate-200/80 bg-white text-slate-700'
                  }`}
                >
                  <div className="flex items-center gap-2.5 flex-1 min-w-0">
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                        isCorrect
                          ? 'bg-emerald-600 text-white'
                          : 'border border-slate-300 text-slate-600'
                      }`}
                    >
                      {String.fromCharCode(65 + idx)}
                    </span>

                    {isEditing ? (
                      <input
                        type="text"
                        value={opt}
                        onChange={(e) => handleOptionChange(idx, e.target.value)}
                        className="w-full bg-transparent text-[13.5px] text-slate-900 focus:outline-none"
                      />
                    ) : (
                      <span className="truncate">{opt}</span>
                    )}
                  </div>

                  {isCorrect && (
                    <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-100/60 px-2 py-0.5 rounded">
                      Correct Answer
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Explanation */}
        {(question.explanation || isEditing) && (
          <div className="rounded-lg bg-slate-50 border border-slate-100 p-3.5 text-[13px] text-slate-600 leading-relaxed">
            <span className="font-semibold text-slate-700 block mb-1 text-[13px]">Explanation:</span>
            {isEditing ? (
              <textarea
                value={explanation}
                onChange={(e) => setExplanation(e.target.value)}
                rows={2}
                className="w-full rounded-md border border-slate-200 bg-white p-2 text-[13px] text-slate-800"
              />
            ) : (
              <p>{question.explanation}</p>
            )}
          </div>
        )}

        {/* Expandable Source Information */}
        {primarySource && (
          <div className="rounded-lg border border-slate-100 bg-slate-50/60">
            <button
              type="button"
              onClick={() => setShowSource(!showSource)}
              className="w-full flex items-center justify-between px-3.5 py-2 text-[12.5px] text-slate-600 hover:text-slate-900 transition-colors"
            >
              <div className="flex items-center gap-2">
                <Bookmark className="h-3.5 w-3.5 text-blue-600" />
                <span>
                  Source: <strong className="font-semibold text-slate-800">{primarySource.document_title || 'QShala Archive'}</strong> · Slide {primarySource.slide_number || 'N/A'}
                </span>
              </div>
              {showSource ? (
                <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
              )}
            </button>

            {showSource && (
              <div className="border-t border-slate-100 p-3.5 text-[12px] text-slate-600 space-y-2">
                <p className="font-mono text-[12px] bg-white p-2.5 rounded-md border border-slate-200 text-slate-700 leading-relaxed">
                  {primarySource.source_quote || 'Historical evidence indexed in knowledge base.'}
                </p>
                <div className="flex justify-end">
                  <button
                    onClick={() => onViewSource(primarySource)}
                    className="flex items-center gap-1 text-[12px] font-semibold text-blue-600 hover:text-blue-700 transition-colors"
                  >
                    <span>View Original Slide</span>
                    <ExternalLink className="h-3 w-3" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action Toolbar */}
      <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3.5 text-[13px]">
        <div className="flex items-center gap-2">
          {isEditing ? (
            <button
              onClick={handleSave}
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 font-semibold text-white hover:bg-blue-700 transition-colors"
            >
              <Check className="h-3.5 w-3.5" />
              <span>Save</span>
            </button>
          ) : (
            <button
              onClick={() => setIsEditing(true)}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 transition-colors"
            >
              <Edit2 className="h-3.5 w-3.5 text-slate-400" />
              <span>Edit</span>
            </button>
          )}

          <button
            onClick={() => handleAction('regenerate')}
            disabled={actionLoading !== null}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 text-slate-400 ${actionLoading === 'regenerate' ? 'animate-spin text-blue-600' : ''}`} />
            <span>Regenerate</span>
          </button>

          <button
            onClick={() => handleAction('make_easier')}
            disabled={actionLoading !== null}
            className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            <TrendingDown className="h-3.5 w-3.5 text-slate-400" />
            <span>Make easier</span>
          </button>

          <button
            onClick={() => handleAction('make_harder')}
            disabled={actionLoading !== null}
            className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            <TrendingUp className="h-3.5 w-3.5 text-slate-400" />
            <span>Make harder</span>
          </button>
        </div>

        <button
          onClick={() => onDelete(question.id)}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 transition-colors"
          title="Delete Question"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
