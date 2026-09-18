'use client';

import { useState, useEffect, useRef } from 'react';
import {
  UploadCloud,
  FileText,
  Trash2,
  CheckCircle2,
  Loader2,
  ArrowRight,
} from 'lucide-react';
import { api } from '../../lib/api';
import { DocumentItem } from '../../lib/types';
import SlideViewerModal from '../../components/SlideViewerModal';

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
  } | null>(null);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
        });

        if (status.status === 'COMPLETED' || status.status === 'FAILED') {
          clearInterval(interval);
          setActiveDocId(null);
          fetchDocuments();
        }
      } catch (e) {
        console.error(e);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [activeDocId]);

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    try {
      const doc = await api.uploadDocument(file);
      setActiveDocId(doc.id);
      setPipelineProgress({
        step: 'Uploading',
        percentage: 15,
        slides: 0,
        questions: 0,
        status: 'PROCESSING',
      });
      fetchDocuments();
    } catch (err: any) {
      alert(err.message || 'Upload failed');
    } finally {
      setUploading(false);
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
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

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
          accept=".pptx,.ppt,.pdf"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
        />

        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600 mb-3 group-hover:scale-105 transition-transform">
          <UploadCloud className="h-6 w-6" />
        </div>

        <h3 className="text-[16px] font-bold text-slate-900">Add new quiz material</h3>
        <p className="mt-1 text-[13px] text-slate-500 max-w-sm font-normal leading-relaxed">
          Drag and drop your PowerPoint (<code className="font-mono text-slate-700">.pptx, .ppt</code>) or PDF files here
        </p>

        <div className="mt-4">
          <button
            type="button"
            disabled={uploading}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] sm:text-[14px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm cursor-pointer"
          >
            {uploading ? 'Uploading...' : 'Browse files'}
          </button>
        </div>
      </div>

      {/* Real-time Ingestion Progress */}
      {pipelineProgress && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4 animate-in fade-in">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              <div>
                <h4 className="text-[13px] font-semibold text-slate-900">Processing Material</h4>
                <p className="text-[12px] text-slate-500 font-normal">{pipelineProgress.step}</p>
              </div>
            </div>

            <span className="text-[14px] font-bold text-blue-600">
              {pipelineProgress.percentage}%
            </span>
          </div>

          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full bg-blue-600 transition-all duration-300"
              style={{ width: `${pipelineProgress.percentage}%` }}
            />
          </div>

          {/* 5 Clean Steps */}
          <div className="grid grid-cols-5 gap-2 pt-2 text-center text-xs">
            {cleanSteps.map((step, idx) => {
              const isPast = pipelineProgress.percentage >= ((idx + 1) / 5) * 100;
              const isCurrent =
                pipelineProgress.percentage >= (idx / 5) * 100 && !isPast;

              return (
                <div key={step} className="space-y-1">
                  <div
                    className={`h-1 rounded-full ${
                      isPast
                        ? 'bg-emerald-500'
                        : isCurrent
                        ? 'bg-blue-600'
                        : 'bg-slate-200'
                    }`}
                  />
                  <span
                    className={`text-[12px] ${
                      isCurrent
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

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5 text-[12px]">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      doc.processing_status === 'COMPLETED'
                        ? 'bg-emerald-500'
                        : doc.processing_status === 'FAILED'
                        ? 'bg-red-500'
                        : 'bg-blue-500 animate-pulse'
                    }`}
                  />
                  <span className="text-[12px] font-medium text-slate-600">
                    {doc.processing_status === 'COMPLETED' ? 'Completed' : doc.processing_status}
                  </span>
                </div>

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
