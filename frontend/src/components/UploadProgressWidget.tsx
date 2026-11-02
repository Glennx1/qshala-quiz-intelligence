'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Loader2, CheckCircle2, AlertCircle, X, ArrowRight } from 'lucide-react';
import { useUpload } from '../context/UploadContext';

export default function UploadProgressWidget() {
  const pathname = usePathname();
  const {
    activeBatchId,
    items,
    summary,
    pipelineProgress,
    activeFileName,
    dismissProgress,
  } = useUpload();

  // If user is already on the uploads page, don't show the floating widget
  if (pathname === '/uploads') return null;

  const hasBatch = Boolean(activeBatchId && items.length > 0);
  if (!hasBatch && !pipelineProgress) return null;

  const completedCount = items.filter((it) => it.phase === 'COMPLETED').length;
  const failedCount = items.filter((it) => it.phase === 'FAILED').length;
  const isAllBatchDone =
    hasBatch &&
    items.every(
      (it) => it.phase === 'COMPLETED' || it.phase === 'FAILED' || it.phase === 'CANCELLED'
    );

  const pct =
    hasBatch && items.length > 0
      ? Math.round((completedCount / items.length) * 100)
      : pipelineProgress?.percentage || 0;

  return (
    <div className="fixed bottom-5 right-5 z-50 w-96 max-w-[calc(100vw-2rem)] animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div
        className={`rounded-2xl border p-4 shadow-xl backdrop-blur-md transition-all ${
          isAllBatchDone
            ? 'border-emerald-200 bg-white/95 shadow-emerald-500/10'
            : failedCount > 0 && isAllBatchDone
            ? 'border-rose-200 bg-white/95 shadow-rose-500/10'
            : 'border-slate-200/90 bg-white/95 shadow-slate-900/10'
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5 min-w-0">
            <div className="mt-0.5 shrink-0">
              {isAllBatchDone ? (
                failedCount > 0 ? (
                  <AlertCircle className="h-5 w-5 text-rose-600" />
                ) : (
                  <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                )
              ) : (
                <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
              )}
            </div>
            <div className="min-w-0">
              <h4 className="text-[13px] font-semibold text-slate-900 truncate">
                {hasBatch ? 'Batch Ingestion' : activeFileName || 'Slide Deck'}
              </h4>
              <p className="text-[11.5px] text-slate-500 truncate mt-0.5">
                {hasBatch ? summary : pipelineProgress?.step || 'Processing...'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span
              className={`text-[13px] font-bold tabular-nums ${
                isAllBatchDone ? 'text-emerald-600' : 'text-blue-600'
              }`}
            >
              {pct}%
            </span>

            {isAllBatchDone && (
              <button
                type="button"
                onClick={dismissProgress}
                className="rounded-md p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
                title="Dismiss"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full transition-all duration-300 ${
              isAllBatchDone ? 'bg-emerald-600' : 'bg-blue-600'
            }`}
            style={{ width: `${Math.max(pct, 5)}%` }}
          />
        </div>

        {/* Link to view uploads queue */}
        <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5 text-[11.5px]">
          <Link
            href="/uploads"
            className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-700 transition-colors"
          >
            <span>View batch queue</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
          {hasBatch && (
            <span className="text-slate-400">
              {completedCount} of {items.length} completed
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
