'use client';

import { useEffect, useState } from 'react';
import { Settings as SettingsIcon, Database, Cpu, ShieldCheck, HardDrive } from 'lucide-react';
import { getApiBase } from '@/lib/api';

export default function SettingsPage() {
  const [apiEndpoint, setApiEndpoint] = useState('/api/v1');

  useEffect(() => {
    setApiEndpoint(getApiBase());
  }, []);
  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-4xl mx-auto space-y-7 pb-20">
      <div>
        <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
          Settings
        </h1>
        <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
          Manage platform parameters, AI model connections, and vector storage.
        </p>
      </div>

      {/* AI Provider Settings */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-6 shadow-sm shadow-slate-100/50 space-y-4">
        <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
          <Cpu className="h-4 w-4 text-blue-600" />
          <h2 className="text-[16px] font-semibold text-slate-900">AI & Embeddings Engine</h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-[13px]">
          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">
              LLM Provider
            </span>
            <div className="font-semibold text-[14px] text-slate-900">Local Engine (Deterministic & Grounded)</div>
            <p className="text-[12px] text-slate-400 font-normal">
              Swappable to Google Gemini or OpenAI via <code className="font-mono">.env</code>
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">
              Vector Dimension
            </span>
            <div className="font-semibold text-[14px] text-slate-900">768-dimensional Unit Vectors</div>
            <p className="text-[12px] text-slate-400 font-normal">
              Compatible with pgvector and text-embedding-004
            </p>
          </div>
        </div>
      </div>

      {/* Validation Pipeline Thresholds */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-6 shadow-sm shadow-slate-100/50 space-y-4">
        <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
          <ShieldCheck className="h-4 w-4 text-emerald-600" />
          <h2 className="text-[16px] font-semibold text-slate-900">7-Stage Validation Pipeline</h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-[13px]">
          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="text-[12px] font-semibold text-slate-500">Duplicate Similarity Limit</span>
            <div className="text-[24px] font-bold text-slate-900 leading-tight">85%</div>
            <p className="text-[12px] text-slate-400 font-normal">Threshold for triggering duplicate warnings</p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="text-[12px] font-semibold text-slate-500">Min Factual Grounding</span>
            <div className="text-[24px] font-bold text-slate-900 leading-tight">70%</div>
            <p className="text-[12px] text-slate-400 font-normal">Requires slide source corroboration</p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="text-[12px] font-semibold text-slate-500">Distractor Consistency</span>
            <div className="text-[24px] font-bold text-slate-900 leading-tight">4-Option MCQ</div>
            <p className="text-[12px] text-slate-400 font-normal">Enforces mutual exclusivity</p>
          </div>
        </div>
      </div>

      {/* Storage & Engine Status */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-6 shadow-sm shadow-slate-100/50 space-y-4">
        <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
          <HardDrive className="h-4 w-4 text-slate-600" />
          <h2 className="text-[16px] font-semibold text-slate-900">Database & System Health</h2>
        </div>

        <div className="divide-y divide-slate-100 text-[13px]">
          <div className="flex items-center justify-between py-2.5">
            <span className="text-slate-600 font-normal">Backend API Status</span>
            <span className="flex items-center gap-1.5 font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded text-[12px]">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              <span>Online ({apiEndpoint})</span>
            </span>
          </div>

          <div className="flex items-center justify-between py-2.5">
            <span className="text-slate-600 font-normal">Historical Corpus Storage</span>
            <span className="font-mono text-slate-700 text-[12px]">backend/storage/uploads</span>
          </div>

          <div className="flex items-center justify-between py-2.5">
            <span className="text-slate-600 font-normal">Platform Version</span>
            <span className="font-mono text-slate-700 text-[12px]">v1.2.0 (SaaS Edition)</span>
          </div>
        </div>
      </div>
    </div>
  );
}
