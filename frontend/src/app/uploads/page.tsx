'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import {
  UploadCloud,
  FileText,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ArrowRight,
  X,
  Clock,
  ListOrdered,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import { api, isAbortError, UPLOAD_CHUNK_SIZE, UploadProgressInfo } from '../../lib/api';
import { DocumentItem } from '../../lib/types';
import SlideViewerModal from '../../components/SlideViewerModal';
import { optimizeDeckInBrowser } from '../../lib/deckOptimizer';

export default function UploadPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [pipelineProgress, setPipelineProgress] = useState<{
    step: string;
    percentage: number;
    slides: number;
    questions: number;
    status: string;
    detail?: string | null;
    events?: { ts: number; msg: string }[];
    memory?: { cur?: number | null; peak?: number | null; limit?: number | null };
    error?: string | null;
  } | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Live upload numbers (slice i of N, MB sent) and the handles needed to cancel for real
  const [uploadDetail, setUploadDetail] = useState<UploadProgressInfo | null>(null);
  const [uploadQueueStatus, setUploadQueueStatus] = useState<{
    total: number;
    completed: number;
    currentFileName: string;
  } | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const uploadIdRef = useRef<string | null>(null);

  const fmtMB = (bytes: number) => (bytes / (1024 * 1024)).toFixed(1);

  // Stopwatch for the whole run: starts when the upload starts, stops when ingestion ends
  // (COMPLETED = fully tagged and stored, FAILED, or CANCELLED). uploadEndedAt splits it into phases.
  const [timing, setTiming] = useState<{
    startedAt: number;
    uploadEndedAt: number | null;
    finishedAt: number | null;
  } | null>(null);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!timing || timing.finishedAt) return;
    const id = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(id);
  }, [timing]);

  const fmtDuration = (ms: number) => {
    const total = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${m}:${String(s).padStart(2, '0')}`;
  };
  const stopClock = () =>
    setTiming((t) => (t && !t.finishedAt ? { ...t, finishedAt: Date.now() } : t));

  const cleanSteps = [
    'Uploading',
    'Extracting slides',
    'Identifying questions',
    'Indexing knowledge',
    'Ready',
  ];

  const fetchDocuments = async () => {
    try {
      const data = await api.listDocuments();
      setDocuments(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  // Poll status when active upload is processing
  useEffect(() => {
    if (!activeDocId) return;

    const interval = setInterval(async () => {
      try {
        const status = await api.getIngestionStatus(activeDocId);
        setPipelineProgress({
          step: status.current_step,
          percentage: status.progress_percentage,
          slides: status.slides_processed,
          questions: status.questions_extracted,
          status: status.status,
          detail: status.detail,
          events: status.events || [],
          memory: { cur: status.memory_mb, peak: status.peak_memory_mb, limit: status.memory_limit_mb },
          error: status.error,
        });

        if (status.status === 'COMPLETED' || status.status === 'FAILED' || status.status === 'CANCELLED') {
          clearInterval(interval);
          setActiveDocId(null);
          setCancelling(false);
          stopClock();
          fetchDocuments();
        }
      } catch (e) {
        console.error(e);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [activeDocId]);

  // Auto-poll documents list if any document is currently in QUEUED or PROCESSING state
  useEffect(() => {
    const hasPending = documents.some(
      (d) => d.processing_status === 'QUEUED' || d.processing_status === 'PROCESSING'
    );
    if (!hasPending && !activeDocId && !uploading) return;

    const interval = setInterval(() => {
      fetchDocuments();
    }, 2000);

    return () => clearInterval(interval);
  }, [documents, activeDocId, uploading]);

  // Auto-connect to active processing document if activeDocId is null (e.g. after refresh or queue transition)
  useEffect(() => {
    if (!activeDocId) {
      const processing = documents.find((d) => d.processing_status === 'PROCESSING');
      if (processing) {
        setActiveDocId(processing.id);
        if (!timing || timing.finishedAt) {
          setTiming({ startedAt: Date.now(), uploadEndedAt: Date.now(), finishedAt: null });
        }
      }
    }
  }, [documents, activeDocId, timing]);

  const [retryingId, setRetryingId] = useState<string | null>(null);

  const handleRetry = async (id: string) => {
    setRetryingId(id);
    try {
      await api.retryDocument(id);
      await fetchDocuments();
    } catch (err: any) {
      alert(err.message || 'Failed to retry deck ingestion');
    } finally {
      setRetryingId(null);
    }
  };

  const handleFileUpload = async (file: File, fileIndex = 1, fileTotal = 1) => {
    const controller = new AbortController();
    abortRef.current = controller;
    uploadIdRef.current = null;
    setCancelling(false);
    setTiming({ startedAt: Date.now(), uploadEndedAt: null, finishedAt: null });
    setUploading(true);
    const mbSize = fmtMB(file.size);

    // The backend runs on Render (not Vercel serverless), so there is no 4.5 MB payload ceiling.
    // Decks up to 50 MB go up in one request; larger ones are sent as 50 MB slices so a dropped
    // connection only costs one slice, and Cancel can stop between/inside slices.
    const isLocalhost =
      typeof window !== 'undefined' &&
      (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');
    const directUploadLimit = isLocalhost ? 100 * 1024 * 1024 : UPLOAD_CHUNK_SIZE;
    const sliceMB = Math.round(UPLOAD_CHUNK_SIZE / (1024 * 1024));
    const batchPrefix = fileTotal > 1 ? `[${fileIndex}/${fileTotal}] ` : '';

    try {
      let doc: DocumentItem;

      if (file.size > directUploadLimit) {
        const plannedSlices = Math.ceil(file.size / UPLOAD_CHUNK_SIZE);
        setUploadDetail({
          bytesSent: 0,
          totalBytes: file.size,
          chunkIndex: 1,
          totalChunks: plannedSlices,
          chunkSize: UPLOAD_CHUNK_SIZE,
        });
        setPipelineProgress({
          step: `${batchPrefix}Uploading ${file.name} (${mbSize} MB) in ${plannedSlices} slices of ${sliceMB} MB...`,
          percentage: 5,
          slides: 0,
          questions: 0,
          status: 'PROCESSING',
        });

        doc = await api.uploadDocumentChunked(
          file,
          (pct, currentChunk, totalChunks, info) => {
            setUploadDetail(info);
            setPipelineProgress({
              step: `${batchPrefix}Uploading ${file.name} slice ${currentChunk} of ${totalChunks} (${pct}% of ${mbSize} MB)...`,
              percentage: Math.min(Math.round(5 + pct * 0.2), 25), // 5% to 25% for upload stage
              slides: 0,
              questions: 0,
              status: 'PROCESSING',
            });
          },
          undefined,
          undefined,
          undefined,
          { signal: controller.signal, onUploadId: (id) => { uploadIdRef.current = id; } }
        );
      } else {
        setPipelineProgress({
          step: `${batchPrefix}Uploading ${file.name} (${mbSize} MB) to server...`,
          percentage: 18,
          slides: 0,
          questions: 0,
          status: 'PROCESSING',
        });
        doc = await api.uploadDocument(file, undefined, undefined, {
          signal: controller.signal,
          onProgress: (info) => setUploadDetail(info),
        });
      }

      setUploadDetail(null);
      setTiming((t) => (t ? { ...t, uploadEndedAt: Date.now() } : t));
      setActiveDocId(doc.id);
      await fetchDocuments();
    } catch (err: any) {
      if (isAbortError(err)) {
        stopClock();
        setPipelineProgress({
          step: 'Upload cancelled. Nothing was kept on the server.',
          percentage: 0,
          slides: 0,
          questions: 0,
          status: 'CANCELLED',
        });
      } else {
        alert(err.message || `Upload of ${file.name} failed`);
        setPipelineProgress(null);
        setTiming(null);
      }
    } finally {
      setUploading(false);
      setUploadDetail(null);
      abortRef.current = null;
      setCancelling(false);
    }
  };

  const handleFiles = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) =>
      /\.(pptx|ppt|pdf)$/i.test(f.name)
    );
    if (list.length === 0) {
      alert('Please select valid PowerPoint (.pptx, .ppt) or PDF files.');
      return;
    }

    setUploadQueueStatus({
      total: list.length,
      completed: 0,
      currentFileName: list[0].name,
    });

    for (let i = 0; i < list.length; i++) {
      const file = list[i];
      setUploadQueueStatus({
        total: list.length,
        completed: i,
        currentFileName: file.name,
      });
      await handleFileUpload(file, i + 1, list.length);
    }

    setUploadQueueStatus(null);
    await fetchDocuments();
  };

  // Cancel really stops the work: while slices are still going up it aborts the in-flight request
  // and tells the server to delete the slices already received; once the deck is uploaded and being
  // processed it tells the backend pipeline to stop, which then removes the document and its media.
  const handleCancel = async () => {
    if (cancelling) return;
    setCancelling(true);
    setPipelineProgress((p) => (p ? { ...p, step: 'Cancelling...' } : p));
    try {
      if (abortRef.current) {
        abortRef.current.abort();
        const id = uploadIdRef.current;
        if (id) await api.cancelChunkedUpload(id);
      } else if (activeDocId) {
        const res = await api.cancelIngestion(activeDocId);
        if (res.status === 'CANCELLED') {
          // nothing was running server-side, cleanup already done
          setActiveDocId(null);
          stopClock();
          setPipelineProgress({
            step: 'Upload cancelled. Nothing was kept on the server.',
            percentage: 0,
            slides: 0,
            questions: 0,
            status: 'CANCELLED',
          });
          setCancelling(false);
          fetchDocuments();
        }
        // 'CANCELLING': the status poll picks up CANCELLED once the pipeline has stopped
      }
    } catch (e) {
      console.error(e);
      setCancelling(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this historical document?')) return;
    try {
      await api.deleteDocument(id);
      fetchDocuments();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const queuedDocs = documents
    .filter((d) => d.processing_status === 'QUEUED')
    .slice()
    .reverse();

  const activeDoc = documents.find((d) => d.id === activeDocId);

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
          Upload Center
        </h1>
        <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
          Add new historical quiz material to expand QShala's proprietary knowledge base.
        </p>
      </div>

      {/* Drag & Drop Upload Zone */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-white p-10 text-center hover:border-blue-500 transition-colors cursor-pointer group shadow-sm shadow-slate-100/50"
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pptx,.ppt,.pdf"
          className="hidden"
          onClick={(e) => {
            (e.target as HTMLInputElement).value = '';
          }}
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              handleFiles(e.target.files);
            }
          }}
        />

        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600 mb-3 group-hover:scale-105 transition-transform">
          <UploadCloud className="h-6 w-6" />
        </div>

        <h3 className="text-[16px] font-bold text-slate-900">Add new quiz material</h3>
        <p className="mt-1 text-[13px] text-slate-500 max-w-sm font-normal leading-relaxed">
          Drag and drop one or multiple PowerPoint (<code className="font-mono text-slate-700">.pptx, .ppt</code>) or PDF files here
        </p>

        <div className="mt-4">
          <button
            type="button"
            disabled={uploading}
            onClick={(e) => {
              e.stopPropagation();
              fileInputRef.current?.click();
            }}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] sm:text-[14px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm cursor-pointer disabled:opacity-50"
          >
            {uploading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
                {uploadQueueStatus && uploadQueueStatus.total > 1
                  ? `Uploading ${uploadQueueStatus.completed + 1} of ${uploadQueueStatus.total}...`
                  : 'Uploading...'}
              </span>
            ) : (
              'Browse files (multi-select enabled)'
            )}
          </button>
        </div>
      </div>

      {/* Real-time Ingestion Progress */}
      {pipelineProgress && (
        <div className={`rounded-xl border p-6 shadow-sm space-y-4 animate-in fade-in transition-all ${
          pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100
            ? 'border-emerald-200 bg-emerald-50/25'
            : pipelineProgress.status === 'FAILED'
            ? 'border-rose-200 bg-rose-50/25'
            : pipelineProgress.status === 'CANCELLED'
            ? 'border-amber-200 bg-amber-50/30'
            : 'border-slate-200 bg-white'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100 ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
              ) : pipelineProgress.status === 'FAILED' ? (
                <AlertCircle className="h-5 w-5 text-rose-600 shrink-0" />
              ) : pipelineProgress.status === 'CANCELLED' ? (
                <X className="h-5 w-5 text-amber-600 shrink-0" />
              ) : (
                <Loader2 className="h-5 w-5 animate-spin text-blue-600 shrink-0" />
              )}
              <div>
                <h4 className="text-[13px] font-semibold text-slate-900">
                  {pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100
                    ? `Ingestion Complete${activeDoc ? `: ${activeDoc.title}` : ''}`
                    : pipelineProgress.status === 'FAILED'
                    ? `Ingestion Failed${activeDoc ? `: ${activeDoc.title}` : ''}`
                    : pipelineProgress.status === 'CANCELLED'
                    ? 'Upload Cancelled'
                    : uploadDetail
                    ? `Uploading Material${activeDoc ? `: ${activeDoc.title}` : ''}`
                    : `Processing Deck${activeDoc ? `: ${activeDoc.title}` : ''}`}
                </h4>
                <p className="text-[12px] text-slate-500 font-normal">{pipelineProgress.step}</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <span className={`text-[14px] font-bold ${
                pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100
                  ? 'text-emerald-600'
                  : pipelineProgress.status === 'FAILED'
                  ? 'text-rose-600'
                  : 'text-blue-600'
              }`}>
                {pipelineProgress.status === 'CANCELLED' ? '' : `${pipelineProgress.percentage}%`}
              </span>

              {pipelineProgress.status === 'PROCESSING' && (uploading || activeDocId) && (
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={cancelling}
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-[12px] font-semibold text-rose-600 hover:bg-rose-50 transition-colors disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
                  title="Stop this upload and remove everything it created on the server"
                >
                  <X className="h-3.5 w-3.5" />
                  {cancelling ? 'Cancelling...' : 'Cancel upload'}
                </button>
              )}

              {(pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100 || pipelineProgress.status === 'FAILED' || pipelineProgress.status === 'CANCELLED') && (
                <button
                  type="button"
                  onClick={() => setPipelineProgress(null)}
                  className="rounded-lg p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
                  title="Dismiss notification"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>

          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full transition-all duration-300 ${
                pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100
                  ? 'bg-emerald-600'
                  : pipelineProgress.status === 'FAILED'
                  ? 'bg-rose-600'
                  : pipelineProgress.status === 'CANCELLED'
                  ? 'bg-amber-500'
                  : 'bg-blue-600'
              }`}
              style={{ width: `${pipelineProgress.percentage}%` }}
            />
          </div>

          {/* Live upload detail: which slice is going up and how many MB have been sent */}
          {uploadDetail && pipelineProgress.status === 'PROCESSING' && (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[12px]">
                <span className="font-semibold text-slate-800">
                  {uploadDetail.totalChunks > 1
                    ? `Slice ${uploadDetail.chunkIndex} of ${uploadDetail.totalChunks}`
                    : 'Uploading in one piece'}
                </span>
                <span className="text-slate-500 font-normal tabular-nums">
                  {fmtMB(uploadDetail.bytesSent)} / {fmtMB(uploadDetail.totalBytes)} MB
                  {uploadDetail.totalChunks > 1 && ` · ${fmtMB(uploadDetail.chunkSize)} MB per slice`}
                </span>
              </div>
              <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full bg-blue-400 transition-all duration-200"
                  style={{
                    width: `${uploadDetail.totalBytes > 0 ? Math.round((uploadDetail.bytesSent / uploadDetail.totalBytes) * 100) : 0}%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Stopwatch: ticks from upload start until tagging is fully done */}
          {timing && (
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[12px]">
              <span className="font-semibold text-slate-800 tabular-nums">
                {timing.finishedAt
                  ? pipelineProgress.status === 'COMPLETED'
                    ? `Finished in ${fmtDuration(timing.finishedAt - timing.startedAt)}`
                    : `Stopped after ${fmtDuration(timing.finishedAt - timing.startedAt)}`
                  : `Elapsed ${fmtDuration(Date.now() - timing.startedAt)}`}
              </span>
              <span className="text-slate-500 font-normal tabular-nums">
                {`Upload ${fmtDuration((timing.uploadEndedAt ?? timing.finishedAt ?? Date.now()) - timing.startedAt)}`}
                {timing.uploadEndedAt &&
                  ` · Extract, tag & index ${fmtDuration((timing.finishedAt ?? Date.now()) - timing.uploadEndedAt)}`}
              </span>
            </div>
          )}

          {/* What the server is doing right now, its memory, and a short activity log */}
          {pipelineProgress.status === 'PROCESSING' && (pipelineProgress.detail || (pipelineProgress.events || []).length > 0) && (
            <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <p className="text-[12.5px] font-semibold text-slate-800 leading-snug">
                  {pipelineProgress.detail || pipelineProgress.step}
                </p>
                {pipelineProgress.memory?.cur != null && (() => {
                  const cur = pipelineProgress.memory!.cur as number;
                  const limit = pipelineProgress.memory!.limit || 0;
                  const ratio = limit ? cur / limit : 0;
                  const cls = ratio > 0.92 ? 'bg-red-100 text-red-700' : ratio > 0.8 ? 'bg-amber-100 text-amber-800' : 'bg-slate-200 text-slate-700';
                  return (
                    <span className={`rounded px-2 py-0.5 text-[11px] font-semibold tabular-nums ${cls}`} title="Memory used by the server process. If this reaches the limit the server restarts and the upload is lost.">
                      Server memory {Math.round(cur)} MB{limit ? ` of ${Math.round(limit)} MB` : ''}
                      {pipelineProgress.memory?.peak != null && ` · peak ${Math.round(pipelineProgress.memory.peak as number)} MB`}
                    </span>
                  );
                })()}
              </div>
              {(pipelineProgress.events || []).length > 0 && (
                <div>
                  <button type="button" onClick={() => setShowLog((v) => !v)} className="text-[11.5px] font-semibold text-blue-600 hover:text-blue-700 cursor-pointer">
                    {showLog ? 'Hide activity log' : `Show activity log (${(pipelineProgress.events || []).length})`}
                  </button>
                  {showLog && (
                    <ul className="mt-1.5 max-h-44 space-y-0.5 overflow-y-auto font-mono text-[11px] text-slate-600">
                      {[...(pipelineProgress.events || [])].reverse().map((e, i) => (
                        <li key={i} className="flex gap-2">
                          <span className="shrink-0 text-slate-400 tabular-nums">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
                          <span className="break-words">{e.msg}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 5 Clean Steps */}
          <div className={`grid grid-cols-5 gap-2 pt-2 text-center text-xs ${pipelineProgress.status === 'CANCELLED' ? 'hidden' : ''}`}>
            {cleanSteps.map((step, idx) => {
              const isFinished = pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100;
              const isPast = pipelineProgress.percentage >= ((idx + 1) / 5) * 100;
              const isCurrent =
                pipelineProgress.percentage >= (idx / 5) * 100 && !isPast;

              return (
                <div key={step} className="space-y-1">
                  <div
                    className={`h-1 rounded-full ${
                      isFinished || isPast
                        ? 'bg-emerald-500'
                        : isCurrent
                        ? 'bg-blue-600'
                        : 'bg-slate-200'
                    }`}
                  />
                  <span
                    className={`text-[12px] ${
                      isFinished
                        ? 'text-emerald-700 font-medium'
                        : isCurrent
                        ? 'font-bold text-blue-600'
                        : isPast
                        ? 'text-slate-700 font-medium'
                        : 'text-slate-400'
                    }`}
                  >
                    {step}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Action links upon completion */}
          {(pipelineProgress.status === 'COMPLETED' || pipelineProgress.percentage >= 100) && (
            <div className="flex items-center justify-between pt-2 border-t border-emerald-100">
              <span className="text-[12px] text-emerald-700 font-medium">
                {pipelineProgress.questions > 0
                  ? `${pipelineProgress.questions} questions extracted & indexed into Knowledge Base`
                  : 'Document processed successfully'}
              </span>
              <div className="flex items-center gap-2">
                <Link
                  href="/knowledge-base"
                  className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-blue-700 transition-colors shadow-xs"
                >
                  <span>View Questions</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
                <button
                  type="button"
                  onClick={() => setPipelineProgress(null)}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 hover:bg-slate-50 transition-colors"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Waiting in Serial Queue */}
      {queuedDocs.length > 0 && (
        <div className="rounded-xl border border-amber-200/80 bg-amber-50/20 p-5 shadow-xs space-y-3 animate-in fade-in">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200/60 pb-3">
            <div className="flex items-center gap-2 text-amber-900 font-semibold text-[13.5px]">
              <ListOrdered className="h-4 w-4 text-amber-600" />
              <span>Ingestion Queue ({queuedDocs.length} presentation{queuedDocs.length > 1 ? 's' : ''} waiting)</span>
            </div>
            <span className="text-[11.5px] font-medium text-amber-800 bg-amber-100/80 border border-amber-200 px-2.5 py-0.5 rounded-full">
              Serial Queue: Ingests 1 deck at a time to prevent server memory crashes
            </span>
          </div>

          <div className="divide-y divide-amber-100/60 rounded-lg border border-amber-200/60 bg-white overflow-hidden shadow-xs">
            {queuedDocs.map((doc, idx) => (
              <div key={doc.id} className="flex items-center justify-between px-4 py-3 hover:bg-amber-50/30 transition-colors">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-800 text-[11px] font-bold">
                    #{idx + 1}
                  </span>
                  <div className="min-w-0">
                    <h5 className="truncate text-[13px] font-medium text-slate-900">{doc.title}</h5>
                    <p className="text-[11px] text-slate-500">
                      {doc.slide_count ? `${doc.slide_count} slides • ` : ''}
                      Waiting in line — will begin automatically
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 shrink-0">
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                    <Clock className="h-3 w-3 animate-spin" />
                    Position #{idx + 1}
                  </span>
                  <button
                    onClick={() => handleDelete(doc.id)}
                    className="p-1.5 text-slate-400 hover:text-red-600 rounded transition-colors cursor-pointer"
                    title="Remove from queue"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Ingested Decks Table */}
      <div className="rounded-xl border border-slate-200/80 bg-white shadow-sm shadow-slate-100/50 overflow-hidden">
        <div className="border-b border-slate-100 px-6 py-4 flex items-center justify-between">
          <h2 className="text-[16px] font-semibold tracking-tight text-slate-900">Recent uploads</h2>
          <span className="text-[12px] text-slate-500 font-normal">{documents.length} presentations</span>
        </div>

        <div className="divide-y divide-slate-100">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center justify-between px-6 py-4 hover:bg-slate-50/60 transition-colors"
            >
              <div className="flex items-center gap-3.5 min-w-0">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
                  <FileText className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <h4 className="truncate text-[14px] font-medium text-slate-900">{doc.title}</h4>
                  <p className="text-[12px] text-slate-400 font-normal">
                    {doc.slide_count} slides · {doc.question_count} questions extracted · Year: {doc.year || '2024'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <div className="flex items-center gap-1.5 text-[12px]">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      doc.processing_status === 'COMPLETED'
                        ? 'bg-emerald-500'
                        : doc.processing_status === 'FAILED'
                        ? 'bg-red-500'
                        : doc.processing_status === 'QUEUED'
                        ? 'bg-amber-500 animate-pulse'
                        : 'bg-blue-500 animate-pulse'
                    }`}
                  />
                  <span className="text-[12px] font-medium text-slate-600">
                    {doc.processing_status === 'COMPLETED'
                      ? 'Completed'
                      : doc.processing_status === 'QUEUED'
                      ? 'In Queue'
                      : doc.processing_status === 'PROCESSING'
                      ? 'Processing'
                      : doc.processing_status}
                  </span>
                </div>

                {doc.processing_status === 'COMPLETED' && doc.question_count > 0 && (
                  <Link
                    href={`/knowledge-base?document_id=${doc.id}`}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11.5px] font-medium text-blue-600 hover:bg-blue-50 hover:border-blue-200 transition-colors shadow-xs"
                    title="View Questions in Knowledge Base"
                  >
                    <span>View Questions</span>
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                )}

                {doc.processing_status === 'FAILED' && (
                  <button
                    onClick={() => handleRetry(doc.id)}
                    disabled={retryingId === doc.id}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11.5px] font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-xs cursor-pointer disabled:opacity-50"
                    title="Retry this deck"
                  >
                    <RotateCcw className={`h-3 w-3 ${retryingId === doc.id ? 'animate-spin text-blue-600' : ''}`} />
                    <span>Retry</span>
                  </button>
                )}

                <button
                  onClick={() => handleDelete(doc.id)}
                  className="rounded-lg p-1.5 text-slate-400 hover:text-red-600 transition-colors cursor-pointer"
                  title="Delete Document"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}

          {documents.length === 0 && !loading && (
            <div className="py-12 text-center text-[13px] text-slate-400 font-normal">
              No documents uploaded yet.
            </div>
          )}
        </div>
      </div>

      <SlideViewerModal
        isOpen={Boolean(selectedSlide)}
        onClose={() => setSelectedSlide(null)}
        slide={selectedSlide}
      />
    </div>
  );
}
