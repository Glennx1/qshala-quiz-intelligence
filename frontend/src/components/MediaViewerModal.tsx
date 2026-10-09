'use client';

import React, { useState } from 'react';
import {
  X,
  Image as ImageIcon,
  Volume2,
  Video,
  FileText,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Maximize2
} from 'lucide-react';
import { HistoricalQuestion } from '../lib/types';
import { resolveMediaUrl } from '../lib/api';

interface MediaViewerModalProps {
  question: HistoricalQuestion | null;
  onClose: () => void;
}

export default function MediaViewerModal({ question, onClose }: MediaViewerModalProps) {
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [fullscreenImage, setFullscreenImage] = useState<string | null>(null);
  const [imageErrors, setImageErrors] = useState<Record<string, boolean>>({});
  const [fallbackUrls, setFallbackUrls] = useState<Record<string, string>>({});

  const getImageSrc = (rawUrl: string) => {
    if (!rawUrl) return '';
    if (fallbackUrls[rawUrl]) {
      return fallbackUrls[rawUrl];
    }
    return resolveMediaUrl(rawUrl);
  };

  const handleImageError = (rawUrl: string) => {
    const current = getImageSrc(rawUrl);
    if (current.includes('/static/') && !current.includes('/api/v1/static/')) {
      const altUrl = current.replace('/static/', '/api/v1/static/');
      setFallbackUrls((prev) => ({ ...prev, [rawUrl]: altUrl }));
    } else {
      setImageErrors((prev) => ({ ...prev, [rawUrl]: true }));
    }
  };

  if (!question) return null;

  const images = question.image_refs || [];
  const hasImages = images.length > 0;
  const hasAudio = Boolean(question.audio_transcript || (question.raw_media_refs && question.raw_media_refs.some(r => r.endsWith('.mp3') || r.endsWith('.wav'))));
  const hasVideo = Boolean(question.video_transcript || (question.raw_media_refs && question.raw_media_refs.some(r => r.endsWith('.mp4'))));
  const hasVisualClues = Boolean(question.visual_clues);

  // Find audio/video media URLs from raw_media_refs if available
  const audioRef = (question.raw_media_refs || []).find(r => r.endsWith('.mp3') || r.endsWith('.wav') || r.includes('audio'));
  const videoRef = (question.raw_media_refs || []).find(r => r.endsWith('.mp4') || r.includes('video'));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-150">
      <div
        className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-700 font-bold text-sm">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-[15px] font-bold text-slate-900 leading-tight">
                Multimodal Question Media
              </h3>
              <p className="text-[12px] text-slate-500 font-normal mt-0.5 flex items-center gap-1.5">
                <span>Source:</span>
                <strong className="text-slate-700 font-medium truncate max-w-md">
                  {question.document_title || 'Unknown Presentation'}
                </strong>
                {question.source_slide_range && (
                  <span className="rounded bg-slate-200/80 px-1.5 py-0.2 text-[10.5px] font-semibold text-slate-700">
                    {question.source_slide_range}
                  </span>
                )}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700 transition-colors cursor-pointer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="overflow-y-auto p-6 space-y-6 flex-1">
          {/* Question Text & Answer Bar */}
          <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-4 space-y-2">
            <div className="text-[14px] font-semibold text-slate-900 leading-relaxed">
              {question.question_text}
            </div>
            {question.options && question.options.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                {question.options.map((opt, idx) => (
                  <div key={idx} className="rounded bg-white border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-700">
                    {opt}
                  </div>
                ))}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-200/60 text-[12.5px]">
              <span className="text-slate-500">Verified Answer:</span>
              <span className="font-bold text-emerald-800 bg-emerald-100/70 border border-emerald-200 px-2.5 py-0.5 rounded-md">
                {question.answer}
              </span>
              {question.explanation && (
                <span className="text-slate-500 text-[12px] italic pl-2 border-l border-slate-200">
                  {question.explanation}
                </span>
              )}
            </div>
          </div>

          {/* Section: Slide Images & Visual Clues */}
          {hasImages ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12.5px] font-bold text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
                  <ImageIcon className="h-4 w-4 text-sky-600" />
                  Slide Images ({images.length})
                </span>
                {images.length > 1 && (
                  <span className="text-[12px] text-slate-500">
                    Image {activeImageIndex + 1} of {images.length}
                  </span>
                )}
              </div>

              {/* Main Image Display */}
              <div className="relative rounded-xl border border-slate-200 bg-slate-900/5 overflow-hidden flex items-center justify-center min-h-[260px] max-h-[420px]">
                {imageErrors[images[activeImageIndex]] ? (
                  <div className="flex flex-col items-center justify-center p-8 text-center text-slate-500 min-h-[220px]">
                    <ImageIcon className="h-10 w-10 text-slate-400 mb-2 stroke-1" />
                    <span className="text-[13px] font-semibold text-slate-700">Slide Visual Reference</span>
                    <span className="text-[11px] text-slate-400 mt-0.5 font-mono">
                      {images[activeImageIndex].split('/').pop()}
                    </span>
                    <span className="text-[11.5px] text-slate-500 mt-2 bg-slate-100 rounded-md px-2.5 py-1">
                      {question.source_slide_range ? `From Slides ${question.source_slide_range}` : 'Extracted Question Slide'}
                    </span>
                  </div>
                ) : (
                  <img
                    src={getImageSrc(images[activeImageIndex])}
                    alt={`Slide media ${activeImageIndex + 1}`}
                    className="max-h-[400px] w-auto max-w-full object-contain cursor-zoom-in"
                    onError={() => handleImageError(images[activeImageIndex])}
                    onClick={() => setFullscreenImage(getImageSrc(images[activeImageIndex]))}
                  />
                )}

                {images.length > 1 && (
                  <>
                    <button
                      type="button"
                      onClick={() => setActiveImageIndex((prev) => (prev > 0 ? prev - 1 : images.length - 1))}
                      className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-white/90 shadow-md p-1.5 text-slate-700 hover:bg-white hover:text-black cursor-pointer transition-all"
                    >
                      <ChevronLeft className="h-5 w-5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveImageIndex((prev) => (prev < images.length - 1 ? prev + 1 : 0))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/90 shadow-md p-1.5 text-slate-700 hover:bg-white hover:text-black cursor-pointer transition-all"
                    >
                      <ChevronRight className="h-5 w-5" />
                    </button>
                  </>
                )}

                {!imageErrors[images[activeImageIndex]] && (
                  <button
                    type="button"
                    onClick={() => setFullscreenImage(getImageSrc(images[activeImageIndex]))}
                    className="absolute bottom-2 right-2 rounded-lg bg-black/60 text-white p-1.5 hover:bg-black/80 transition-colors cursor-pointer"
                    title="Expand Fullscreen"
                  >
                    <Maximize2 className="h-4 w-4" />
                  </button>
                )}
              </div>

              {/* Thumbnails row if multiple images */}
              {images.length > 1 && (
                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                  {images.map((img, idx) => {
                    const isErr = imageErrors[img];
                    return (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => setActiveImageIndex(idx)}
                        className={`relative shrink-0 rounded-lg overflow-hidden border-2 h-16 w-20 transition-all cursor-pointer ${
                          activeImageIndex === idx ? 'border-blue-600 ring-2 ring-blue-400' : 'border-slate-200 opacity-70 hover:opacity-100'
                        }`}
                      >
                        {isErr ? (
                          <div className="flex flex-col items-center justify-center h-full w-full bg-slate-100 text-slate-400 text-[10px]">
                            <ImageIcon className="h-4 w-4 mb-0.5" />
                            <span>Img {idx + 1}</span>
                          </div>
                        ) : (
                          <img
                            src={getImageSrc(img)}
                            alt={`thumb ${idx}`}
                            className="h-full w-full object-cover"
                            onError={() => handleImageError(img)}
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ) : null}

          {/* Section: OCR & Visual Clues Description */}
          {hasVisualClues && (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-1.5">
              <span className="text-[12px] font-bold text-indigo-900 uppercase tracking-wider flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-indigo-600" />
                Extracted Visual OCR & Vision Description
              </span>
              <p className="text-[13px] text-indigo-950 whitespace-pre-wrap leading-relaxed">
                {question.visual_clues}
              </p>
            </div>
          )}

          {/* Section: Audio Clue & Playback */}
          {hasAudio && (
            <div className="rounded-xl border border-teal-200 bg-teal-50/40 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-bold text-teal-900 uppercase tracking-wider flex items-center gap-1.5">
                  <Volume2 className="h-4 w-4 text-teal-600" />
                  Embedded Audio Clue
                </span>
                {audioRef && (
                  <span className="text-[11px] font-mono text-teal-700 bg-teal-100/60 px-2 py-0.5 rounded">
                    Audio Part Detected
                  </span>
                )}
              </div>

              {audioRef && (
                <div className="pt-1">
                  <audio controls className="w-full h-10 rounded-lg">
                    <source src={resolveMediaUrl(audioRef)} />
                    Your browser does not support audio playback.
                  </audio>
                </div>
              )}

              {question.audio_transcript && (
                <div className="bg-white/80 rounded-lg p-3 border border-teal-100 text-[13px] text-teal-950">
                  <div className="font-semibold text-teal-800 text-[11px] uppercase tracking-wider mb-1">
                    Speech & Clue Transcript:
                  </div>
                  <div className="italic leading-relaxed">"{question.audio_transcript}"</div>
                </div>
              )}
            </div>
          )}

          {/* Section: Video Clue */}
          {hasVideo && (
            <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-4 space-y-3">
              <span className="text-[12px] font-bold text-violet-900 uppercase tracking-wider flex items-center gap-1.5">
                <Video className="h-4 w-4 text-violet-600" />
                Embedded Video Clue
              </span>

              {videoRef && (
                <div className="pt-1">
                  <video controls className="w-full max-h-64 rounded-lg bg-black">
                    <source src={videoRef} />
                    Your browser does not support video playback.
                  </video>
                </div>
              )}

              {question.video_transcript && (
                <div className="bg-white/80 rounded-lg p-3 border border-violet-100 text-[13px] text-violet-950">
                  <div className="font-semibold text-violet-800 text-[11px] uppercase tracking-wider mb-1">
                    Video Audio Transcript:
                  </div>
                  <div className="italic leading-relaxed">"{question.video_transcript}"</div>
                </div>
              )}
            </div>
          )}

          {/* Empty state if somehow opened on text-only question */}
          {!hasImages && !hasAudio && !hasVideo && !hasVisualClues && (
            <div className="p-8 text-center text-slate-400 text-[13px]">
              This question does not contain extracted visual or audio media files.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/70 px-6 py-3">
          <div className="text-[12px] text-slate-400">
            {question.grade_min && question.grade_max
              ? `Calibrated for Grades ${question.grade_min}–${question.grade_max}`
              : 'General Audience'}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>

      {/* Fullscreen image overlay */}
      {fullscreenImage && (
        <div
          className="fixed inset-0 z-60 flex items-center justify-center bg-black/90 p-4 cursor-zoom-out"
          onClick={() => setFullscreenImage(null)}
        >
          <img
            src={fullscreenImage}
            alt="Fullscreen view"
            className="max-h-[95vh] max-w-[95vw] object-contain rounded-lg"
          />
        </div>
      )}
    </div>
  );
}
