'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  FileText,
  Sparkles,
  ArrowRight,
  MoreVertical,
  Lightbulb,
} from 'lucide-react';
import StatsOverview from '../components/StatsOverview';
import QuickGenerateCard from '../components/QuickGenerateCard';
import { api } from '../lib/api';
import { DashboardStats } from '../lib/types';

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStats = async () => {
    try {
      const data = await api.getStats();
      setStats(data);
    } catch (err) {
      console.error('Error fetching dashboard stats:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-7xl mx-auto space-y-7">
      {/* Welcome Heading */}
      <div>
        <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
          Welcome back, QShala!
        </h1>
        <p className="mt-1.5 text-[15px] text-slate-500 font-normal leading-relaxed">
          Create engaging quizzes using your trusted QShala knowledge base.
        </p>
      </div>

      {/* 4 Statistics Cards */}
      <StatsOverview stats={stats} loading={loading} />

      {/* Main Grid: Create a Quiz (Left) + Right Side Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Create a Quiz */}
        <div className="lg:col-span-8">
          <QuickGenerateCard />
        </div>

        {/* Right Column: Recent Activity & Callout */}
        <div className="lg:col-span-4 space-y-5">
          {/* Recent Knowledge Decks */}
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-100/50">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3 mb-3">
              <h3 className="text-[16px] font-semibold tracking-tight text-slate-900">Recent Knowledge Decks</h3>
              <Link
                href="/uploads"
                className="flex items-center gap-1 text-[12px] font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                <span>View all</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>

            <div className="divide-y divide-slate-50">
              {stats?.recent_documents && stats.recent_documents.length > 0 ? (
                stats.recent_documents.slice(0, 3).map((doc) => (
                  <div key={doc.id} className="flex items-center justify-between py-2.5 group">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                        <FileText className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-slate-900">
                          {doc.title}
                        </p>
                        <p className="text-[12px] text-slate-400 font-normal">
                          {doc.slide_count} slides • {doc.question_count} questions
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0 pl-2">
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                        Completed
                      </span>
                      <button className="text-slate-300 hover:text-slate-500 p-1">
                        <MoreVertical className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-4 text-center text-xs text-slate-400">
                  No documents ingested yet.
                </div>
              )}
            </div>
          </div>

          {/* Recent Generated Quizzes */}
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-100/50">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3 mb-3">
              <h3 className="text-[16px] font-semibold tracking-tight text-slate-900">Recent Generated Quizzes</h3>
              <Link
                href="/quizzes"
                className="flex items-center gap-1 text-[12px] font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                <span>View all</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>

            <div className="divide-y divide-slate-50">
              {stats?.recent_quizzes && stats.recent_quizzes.length > 0 ? (
                stats.recent_quizzes.slice(0, 3).map((quiz) => (
                  <Link
                    key={quiz.id}
                    href={`/quizzes/${quiz.id}`}
                    className="flex items-center justify-between py-2.5 group hover:bg-slate-50/60 rounded-lg px-1 transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                        <Sparkles className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-slate-900 group-hover:text-blue-600 transition-colors">
                          {quiz.title}
                        </p>
                        <p className="text-[12px] text-slate-400 font-normal">
                          {quiz.question_count} questions • {quiz.difficulty}
                        </p>
                      </div>
                    </div>

                    <ArrowRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-blue-600 group-hover:translate-x-0.5 transition-all shrink-0" />
                  </Link>
                ))
              ) : (
                <div className="py-4 text-center text-[13px] text-slate-400">
                  No quizzes generated yet.
                </div>
              )}
            </div>
          </div>

          {/* Need to add new material? Callout card */}
          <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-100 text-blue-600">
                <Lightbulb className="h-4 w-4" />
              </div>
              <div>
                <h4 className="text-[14px] font-semibold text-slate-900">Need to add new material?</h4>
                <p className="mt-1 text-[13px] text-slate-600 leading-relaxed font-normal">
                  Upload your PPT, PPTX or PDF files and they'll be added to your knowledge base
                  automatically.
                </p>
                <Link
                  href="/uploads"
                  className="mt-3 inline-flex items-center gap-1 text-[13px] font-semibold text-blue-600 hover:text-blue-700 transition-colors"
                >
                  <span>Go to Uploads</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
