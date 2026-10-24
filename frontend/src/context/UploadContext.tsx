'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import { api, isAbortError, UPLOAD_CHUNK_SIZE, UploadProgressInfo } from '../lib/api';
import { DocumentItem } from '../lib/types';

export interface PipelineProgress {
  step: string;
  percentage: number;
  slides: number;
  questions: number;
  status: string; // 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  detail?: string | null;
  events?: { ts: number; msg: string }[];
  memory?: { cur?: number | null; peak?: number | null; limit?: number | null };
  error?: string | null;
}

export interface UploadTiming {
  startedAt: number;
  uploadEndedAt: number | null;
  finishedAt: number | null;
}

interface UploadContextType {
  uploading: boolean;
  activeDocId: string | null;
  activeFileName: string | null;
  pipelineProgress: PipelineProgress | null;
  uploadDetail: UploadProgressInfo | null;
  cancelling: boolean;
  timing: UploadTiming | null;
  showLog: boolean;
  setShowLog: React.Dispatch<React.SetStateAction<boolean>>;
  version: number;
  handleFileUpload: (file: File) => Promise<void>;
  handleCancel: () => Promise<void>;
  dismissProgress: () => void;
  fmtMB: (bytes: number) => string;
  fmtDuration: (ms: number) => string;
}

const UploadContext = createContext<UploadContextType | null>(null);

const STORAGE_ACTIVE_KEY = 'qshala_active_upload';

export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [uploading, setUploading] = useState(false);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [activeFileName, setActiveFileName] = useState<string | null>(null);
  const [pipelineProgress, setPipelineProgress] = useState<PipelineProgress | null>(null);
  const [uploadDetail, setUploadDetail] = useState<UploadProgressInfo | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [version, setVersion] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const uploadIdRef = useRef<string | null>(null);

  const [timing, setTiming] = useState<UploadTiming | null>(null);
  const [, setTick] = useState(0);

  // Formatting helpers
  const fmtMB = useCallback((bytes: number) => (bytes / (1024 * 1024)).toFixed(1), []);
  const fmtDuration = useCallback((ms: number) => {
    const total = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${m}:${String(s).padStart(2, '0')}`;
  }, []);

  const stopClock = useCallback(() => {
    setTiming((t) => (t && !t.finishedAt ? { ...t, finishedAt: Date.now() } : t));
  }, []);

  // Live stopwatch tick
  useEffect(() => {
    if (!timing || timing.finishedAt) return;
    const id = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(id);
  }, [timing]);

  // Tab unload warning while slices/bytes are uploading
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (uploading) {
        e.preventDefault();
        e.returnValue = 'An upload is currently sending slices to the server. Leaving will cancel the upload.';
        return e.returnValue;
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [uploading]);

  // Auto-reconnect to any active processing document on initial load or reload
  useEffect(() => {
    let isMounted = true;
    const resumeOngoing = async () => {
      try {
        let savedDocId: string | null = null;
        let savedFileName: string | null = null;
        try {
          const raw = localStorage.getItem(STORAGE_ACTIVE_KEY);
          if (raw) {
            const parsed = JSON.parse(raw);
            savedDocId = parsed.id;
            savedFileName = parsed.fileName;
          }
        } catch {}

        // Check backend documents to see if one is currently PROCESSING
        const docs = await api.listDocuments();
        if (!isMounted) return;

        const processing = docs.find((d) => d.processing_status === 'PROCESSING' || d.id === savedDocId);

        if (processing && processing.processing_status === 'PROCESSING') {
          setActiveDocId(processing.id);
          setActiveFileName(savedFileName || processing.filename || processing.title);
          setPipelineProgress({
            step: 'Processing presentation...',
            percentage: 25,
            slides: 0,
            questions: 0,
            status: 'PROCESSING',
          });
          setTiming((t) => t || { startedAt: Date.now() - 15000, uploadEndedAt: Date.now() - 15000, finishedAt: null });
        } else {
          try {
            localStorage.removeItem(STORAGE_ACTIVE_KEY);
          } catch {}
        }
      } catch (err) {
        console.warn('Could not auto-resume background upload:', err);
      }
    };

    resumeOngoing();
    return () => {
      isMounted = false;
    };
  }, []);

  // Poll status while an active doc is processing on the backend
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
          setVersion((v) => v + 1);
          try {
            localStorage.removeItem(STORAGE_ACTIVE_KEY);
          } catch {}
        }
      } catch (e) {
        console.error('Ingestion polling error:', e);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [activeDocId, stopClock]);

  // Main file upload handler: persists across route navigation
  const handleFileUpload = async (file: File) => {
    const controller = new AbortController();
    abortRef.current = controller;
    uploadIdRef.current = null;
    setCancelling(false);
    setActiveFileName(file.name);
    setTiming({ startedAt: Date.now(), uploadEndedAt: null, finishedAt: null });
    setUploading(true);

    const mbSize = fmtMB(file.size);
    const isLocalhost =
      typeof window !== 'undefined' &&
      (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');
    const directUploadLimit = isLocalhost ? 100 * 1024 * 1024 : UPLOAD_CHUNK_SIZE;
    const sliceMB = Math.round(UPLOAD_CHUNK_SIZE / (1024 * 1024));

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
          step: `Uploading ${file.name} (${mbSize} MB) in ${plannedSlices} slices of ${sliceMB} MB...`,
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
              step: `Uploading slice ${currentChunk} of ${totalChunks} (${pct}% of ${mbSize} MB)...`,
              percentage: Math.min(Math.round(5 + pct * 0.2), 25), // 5% to 25% for upload stage
              slides: 0,
              questions: 0,
              status: 'PROCESSING',
            });
          },
          undefined,
          undefined,
          undefined,
          {
            signal: controller.signal,
            onUploadId: (id) => {
              uploadIdRef.current = id;
            },
          }
        );
      } else {
        setPipelineProgress({
          step: `Uploading ${file.name} (${mbSize} MB) to server...`,
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
      setVersion((v) => v + 1);

      try {
        localStorage.setItem(
          STORAGE_ACTIVE_KEY,
          JSON.stringify({ id: doc.id, fileName: file.name, startedAt: Date.now() })
        );
      } catch {}
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
        alert(err.message || 'Upload failed');
        setPipelineProgress(null);
        setTiming(null);
        setActiveFileName(null);
      }
      try {
        localStorage.removeItem(STORAGE_ACTIVE_KEY);
      } catch {}
    } finally {
      setUploading(false);
      setUploadDetail(null);
      abortRef.current = null;
      setCancelling(false);
    }
  };

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
          setVersion((v) => v + 1);
          try {
            localStorage.removeItem(STORAGE_ACTIVE_KEY);
          } catch {}
        }
      }
    } catch (e) {
      console.error('Cancel upload error:', e);
      setCancelling(false);
    }
  };

  const dismissProgress = () => {
    setPipelineProgress(null);
    setTiming(null);
    setActiveFileName(null);
    try {
      localStorage.removeItem(STORAGE_ACTIVE_KEY);
    } catch {}
  };

  return (
    <UploadContext.Provider
      value={{
        uploading,
        activeDocId,
        activeFileName,
        pipelineProgress,
        uploadDetail,
        cancelling,
        timing,
        showLog,
        setShowLog,
        version,
        handleFileUpload,
        handleCancel,
        dismissProgress,
        fmtMB,
        fmtDuration,
      }}
    >
      {children}
    </UploadContext.Provider>
  );
}

export function useUpload() {
  const ctx = useContext(UploadContext);
  if (!ctx) {
    throw new Error('useUpload must be used within an UploadProvider');
  }
  return ctx;
}
