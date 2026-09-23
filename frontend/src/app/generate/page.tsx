'use client';

import QuickGenerateCard from '../../components/QuickGenerateCard';

export default function GenerateQuizPage() {
  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-4xl mx-auto space-y-7 pb-20">
      <div>
        <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
          Create Quiz
        </h1>
        <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
          Create fresh, age-calibrated quizzes grounded in historical QShala presentations.
        </p>
      </div>

      {/* Main Creation Card */}
      <QuickGenerateCard />
    </div>
  );
}
