'use client';

import React, { useState, useEffect } from 'react';
import { X, FileDown, Loader2, Sparkles, Check, Layout, QrCode } from 'lucide-react';
import { Quiz } from '@/lib/types';
import { ExportOptions } from '@/lib/api';

interface ExportQuizModalProps {
  isOpen: boolean;
  onClose: () => void;
  quiz: Quiz;
  onExport: (format: 'pptx' | 'json' | 'csv', options?: ExportOptions) => Promise<void>;
}

function cleanInitialTitle(rawTitle: string | undefined, topic: string | undefined): string {
  if (!rawTitle || rawTitle.toLowerCase() === 'custom' || rawTitle.toLowerCase() === 'untitled quiz') {
    return topic ? `${topic} Quiz` : 'Bengaluru South Zone';
  }
  let t = rawTitle.trim();
  // Strip common prompt prefixes/suffixes
  t = t.replace(/^(?:give\s+me|generate|create|make|pull)\s+\d*\s*/i, '');
  t = t.replace(/\s*(?:and\s+make\s+a\s+quiz|and\s+create\s+a\s+quiz|make\s+a\s+quiz|create\s+a\s+quiz|quiz\s+please|for\s+school|without\s+images?|text\s+only).*$/i, '');
  t = t.replace(/^questions?\s+(?:on|about|for)\s+/i, '');
  t = t.trim();
  if (t && t.length > 2 && t.toLowerCase() !== rawTitle.trim().toLowerCase()) {
    return `${t.charAt(0).toUpperCase() + t.slice(1)} Quiz`;
  }
  return rawTitle.trim();
}

export default function ExportQuizModal({
  isOpen,
  onClose,
  quiz,
  onExport,
}: ExportQuizModalProps) {
  const [customTitle, setCustomTitle] = useState('');
  const [customSubtitle, setCustomSubtitle] = useState('Preliminary Round Questions & Answers');
  const [theme, setTheme] = useState<'bengaluru_south' | 'minimalist'>('bengaluru_south');
  const [includeSocialSlides, setIncludeSocialSlides] = useState(true);
  const [showAnswerDivider, setShowAnswerDivider] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  useEffect(() => {
    if (quiz) {
      setCustomTitle(cleanInitialTitle(quiz.title, quiz.topic));
    }
  }, [quiz]);

  if (!isOpen) return null;

  const handleDownload = async () => {
    try {
      setIsExporting(true);
      await onExport('pptx', {
        theme,
        customTitle: customTitle.trim() || undefined,
        customSubtitle: customSubtitle.trim() || undefined,
        includeSocialSlides,
        showAnswerDivider,
      });
      onClose();
    } catch (err) {
      console.error('Failed to export presentation:', err);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      <div 
        className="w-full max-w-xl rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 bg-slate-50/70">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-100 text-orange-600">
              <FileDown className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900">Export Presentation (.pptx)</h3>
              <p className="text-xs text-slate-500">Configure tournament title, branding, and slide options</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isExporting}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="space-y-5 px-6 py-5">
          {/* Theme Selector */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
              Presentation Theme
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setTheme('bengaluru_south')}
                className={`flex flex-col items-start p-3.5 rounded-xl border text-left transition ${
                  theme === 'bengaluru_south'
                    ? 'border-orange-500 bg-orange-50/50 shadow-sm ring-1 ring-orange-500/20'
                    : 'border-slate-200 hover:border-slate-300 bg-white'
                }`}
              >
                <div className="flex items-center justify-between w-full mb-1">
                  <span className="text-xs font-bold text-orange-800 uppercase tracking-wider flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-orange-600" />
                    Tournament Master
                  </span>
                  {theme === 'bengaluru_south' && (
                    <div className="h-4 w-4 rounded-full bg-orange-600 text-white flex items-center justify-center">
                      <Check className="h-2.5 w-2.5" />
                    </div>
                  )}
                </div>
                <div className="text-sm font-semibold text-slate-900">Bengaluru South Zone</div>
                <div className="text-xs text-slate-500 mt-0.5">Authentic 16:9 master artwork with Inter typography & QR codes</div>
              </button>

              <button
                type="button"
                onClick={() => setTheme('minimalist')}
                className={`flex flex-col items-start p-3.5 rounded-xl border text-left transition ${
                  theme === 'minimalist'
                    ? 'border-blue-500 bg-blue-50/50 shadow-sm ring-1 ring-blue-500/20'
                    : 'border-slate-200 hover:border-slate-300 bg-white'
                }`}
              >
                <div className="flex items-center justify-between w-full mb-1">
                  <span className="text-xs font-bold text-blue-800 uppercase tracking-wider flex items-center gap-1.5">
                    <Layout className="h-3.5 w-3.5 text-blue-600" />
                    Clean Slate
                  </span>
                  {theme === 'minimalist' && (
                    <div className="h-4 w-4 rounded-full bg-blue-600 text-white flex items-center justify-center">
                      <Check className="h-2.5 w-2.5" />
                    </div>
                  )}
                </div>
                <div className="text-sm font-semibold text-slate-900">Minimalist Modern</div>
                <div className="text-xs text-slate-500 mt-0.5">Dark title frame with high-typography clean layout</div>
              </button>
            </div>
          </div>

          {/* Presentation Title */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
              Deck Title (Slide 1)
            </label>
            <input
              type="text"
              value={customTitle}
              onChange={(e) => setCustomTitle(e.target.value)}
              placeholder="e.g., Bengaluru South Zone, National Prelims 2026"
              className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm font-medium text-slate-900 placeholder:text-slate-400 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/20"
            />
            <p className="mt-1 text-[11px] text-slate-400">
              Rendered in crisp dark 38pt bold typography in the lower half of the title card.
            </p>
          </div>

          {/* Subtitle / Edition */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
              Round / Subtitle
            </label>
            <input
              type="text"
              value={customSubtitle}
              onChange={(e) => setCustomSubtitle(e.target.value)}
              placeholder="e.g., Preliminary Round Questions & Answers, Campus Edition"
              className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm font-medium text-slate-900 placeholder:text-slate-400 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/20"
            />
          </div>

          {/* Options Toggles */}
          {theme === 'bengaluru_south' && (
            <div className="space-y-2.5 rounded-xl bg-slate-50 p-3.5 border border-slate-200/80">
              <label className="flex items-center gap-2.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={includeSocialSlides}
                  onChange={(e) => setIncludeSocialSlides(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500"
                />
                <div className="text-xs text-slate-700">
                  <span className="font-semibold text-slate-900 flex items-center gap-1.5">
                    <QrCode className="h-3.5 w-3.5 text-slate-500" />
                    Include Social Media & QR Code slides
                  </span>
                  <span className="block text-slate-500 text-[11px] mt-0.5">
                    Inserts Slide 2 (#varsityquiz) and Slide 3 (Varsity, Instagram, WhatsApp QR codes)
                  </span>
                </div>
              </label>

              <label className="flex items-center gap-2.5 cursor-pointer select-none border-t border-slate-200/60 pt-2">
                <input
                  type="checkbox"
                  checked={showAnswerDivider}
                  onChange={(e) => setShowAnswerDivider(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500"
                />
                <div className="text-xs text-slate-700">
                  <span className="font-semibold text-slate-900">
                    Include &quot;Answer&quot; Transition slides
                  </span>
                  <span className="block text-slate-500 text-[11px] mt-0.5">
                    Inserts a 3-slide rhythm (Question → &quot;Answer&quot; divider → Reveal). Unchecked keeps agile 2-slide reveal.
                  </span>
                </div>
              </label>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50/70 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isExporting}
            className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-200/60 transition"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleDownload}
            disabled={isExporting}
            className="flex items-center gap-2 rounded-xl bg-orange-600 px-5 py-2.5 text-xs font-semibold text-white shadow-md shadow-orange-500/20 hover:bg-orange-700 transition disabled:opacity-50"
          >
            {isExporting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating PPTX...
              </>
            ) : (
              <>
                <FileDown className="h-4 w-4" />
                Download Presentation (.pptx)
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
