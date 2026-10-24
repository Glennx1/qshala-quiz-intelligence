'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Loader2, CheckCircle2, AlertCircle, X, ArrowRight } from 'lucide-react';
import { useUpload } from '../context/UploadContext';

export default function UploadProgressWidget() {
  const pathname = usePathname();
  const {
    pipelineProgress,
    activeFileName,
    uploadDetail,
    cancelling,
    timing,
    handleCancel,
    dismissProgress,
    fmtMB,
    fmtDuration,
  } = useUpload();

  // If there's no active progress or if the user is already on the uploads page, don't show the floating widget
  if (!pipelineProgress) return null;
  if (pathname === '/uploads') return null;

  const isCompleted = pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100;
  const isFailed = pipelineProgress.status === 'FAILED';
  const isCancelled = pipelineProgress.status === 'CANCELLED';
  const isProcessing = pipelineProgress.status === 'PROCESSING' && !isCompleted;

  return (
    <div className="fixed bottom-5 right-5 z-50 w-96 max-w-[calc(100vw-2rem)] animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div
        className={`rounded-2xl border p-4 shadow-xl backdrop-blur-md transition-all ${
          isCompleted
            ? 'border-emerald-200 bg-white/95 shadow-emerald-500/10'
            : isFailed
            ? 'border-rose-200 bg-white/95 shadow-rose-500/10'
            : isCancelled
            ? 'border-amber-200 bg-white/95 shadow-amber-500/10'
            : 'border-slate-200/90 bg-white/95 shadow-slate-900/10'
        }`}
      >
        {/* Header with status icon, filename, and controls */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5 min-w-0">
            <div className="mt-0.5 shrink-0">
              {isCompleted ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
              ) : isFailed ? (
                <AlertCircle className="h-5 w-5 text-rose-600" />
              ) : isCancelled ? (
                <X className="h-5 w-5 text-amber-600" />
              ) : (
                <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
              )}
            </div>
            <div className="min-w-0">
              <h4 className="text-[13px] font-semibold text-slate-900 truncate">
                {activeFileName || 'Slide Deck'}
              </h4>
              <p className="text-[11.5px] text-slate-500 truncate mt-0.5">
                {pipelineProgress.step}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span
              className={`text-[13px] font-bold tabular-nums ${
                isCompleted
                  ? 'text-emerald-600'
                  : isFailed
                  ? 'text-rose-600'
                  : 'text-blue-600'
              }`}
            >
              {isCancelled ? '' : `${pipelineProgress.percentage}%`}
            </span>

            {isProcessing && (
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelling}
                className="rounded-md p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors disabled:opacity-50"
                title="Cancel upload"
              >
                <X className="h-4 w-4" />
              </button>
            )}

            {!isProcessing && (
              <button
                type="button"
                onClick={dismissProgress}
                className="rounded-md p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                title="Dismiss"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Progress Bar */}
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full transition-all duration-300 ${
              isCompleted
                ? 'bg-emerald-600'
                : isFailed
                ? 'bg-rose-600'
                : isCancelled
                ? 'bg-amber-500'
                : 'bg-blue-600'
            }`}
            style={{ width: `${pipelineProgress.percentage}%` }}
          />
        </div>

        {/* Slice upload details if sending bytes */}
        {uploadDetail && isProcessing && (
          <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500 tabular-nums">
            <span>
              Slice {uploadDetail.chunkIndex} of {uploadDetail.totalChunks}
            </span>
            <span>
              {fmtMB(uploadDetail.bytesSent)} / {fmtMB(uploadDetail.totalBytes)} MB
            </span>
          </div>
        )}

        {/* Footer with elapsed time & link back to uploads page */}
        <div className="mt-3 flex items-center justify-between pt-2 border-t border-slate-100 text-[11.5px]">
          <span className="text-slate-400 tabular-nums">
            {timing
              ? `Elapsed ${fmtDuration(
                  (timing.finishedAt ?? Date.now()) - timing.startedAt
                )}`
              : 'Active'}
          </span>
          <Link
            href="/uploads"
            className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-700 transition-colors"
          >
            <span>View details</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      </div>
    </div>
  );
}
