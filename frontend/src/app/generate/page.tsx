'use client';

import QuickGenerateCard from '../../components/QuickGenerateCard';

export default function GenerateQuizPage() {
  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-4xl mx-auto space-y-7 pb-20">
      <div>
        <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
          Generate Quiz
        </h1>
        <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
          Create fresh, age-calibrated quizzes grounded in historical QShala presentations.
        </p>
      </div>

      {/* Main Creation Card */}
      <QuickGenerateCard />

      {/* Architecture & Mode Details */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-6 shadow-sm shadow-slate-100/50 space-y-3">
        <h3 className="text-[12px] font-semibold text-slate-700 uppercase tracking-wider">
          Generation Modes
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-[13px] text-slate-600">
          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="font-semibold text-[14px] text-slate-900">New (Default)</span>
            <p className="text-[13px] text-slate-500 font-normal leading-relaxed">
              Synthesizes novel questions based on facts, entities, and curricula found in retrieved QShala slides.
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="font-semibold text-[14px] text-slate-900">Remix</span>
            <p className="text-[13px] text-slate-500 font-normal leading-relaxed">
              Takes concepts from historical questions and inverts the perspective (e.g., asking for the ship rather than the captain).
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="font-semibold text-[14px] text-slate-900">Historical</span>
            <p className="text-[13px] text-slate-500 font-normal leading-relaxed">
              Directly curates verbatim questions and answers from original historical slides with provenance links.
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3.5 space-y-1">
            <span className="font-semibold text-[14px] text-slate-900">Similar</span>
            <p className="text-[13px] text-slate-500 font-normal leading-relaxed">
              Models newly synthesized questions after the cognitive depth and distractor construction of top retrieved exemplars.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
