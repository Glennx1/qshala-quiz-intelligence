import { AlertTriangle, X, CheckCircle, Copy } from 'lucide-react';
import { HistoricalQuestion } from '../../lib/types';

// The side-by-side duplicate-candidate review popup (QShala priority plan P3-1). Extracted
// unchanged from knowledge-base/page.tsx's "Duplicate Review & Resolution Modal" section. Takes
// the candidate question as a prop and calls back up for both actions -- the actual resolve
// logic (including what happens to selectedDuplicateForReview on success vs error) stays owned
// by the page/hook, not this component.
export interface DuplicateReviewModalProps {
  question: HistoricalQuestion;
  resolvingId: string | null;
  onClose: () => void;
  onResolve: (id: string, action: 'DISMISS_UNIQUE' | 'CONFIRM_DUPLICATE') => void;
}

export default function DuplicateReviewModal({
  question: selectedDuplicateForReview,
  resolvingId,
  onClose,
  onResolve,
}: DuplicateReviewModalProps) {
  return (
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
            onClick={onClose}
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
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-[13px] font-medium text-slate-700 hover:bg-white transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={resolvingId === selectedDuplicateForReview.id}
            onClick={() => onResolve(selectedDuplicateForReview.id, 'DISMISS_UNIQUE')}
            className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-[13px] font-semibold text-emerald-800 hover:bg-emerald-100 transition-colors cursor-pointer flex items-center gap-1.5"
          >
            <CheckCircle className="h-4 w-4 text-emerald-600" />
            <span>Dismiss as Unique</span>
          </button>
          <button
            type="button"
            disabled={resolvingId === selectedDuplicateForReview.id}
            onClick={() => onResolve(selectedDuplicateForReview.id, 'CONFIRM_DUPLICATE')}
            className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-700 transition-colors cursor-pointer flex items-center gap-1.5"
          >
            <Copy className="h-4 w-4" />
            <span>Confirm Duplicate (Link Provenance)</span>
          </button>
        </div>
      </div>
    </div>
  );
}
