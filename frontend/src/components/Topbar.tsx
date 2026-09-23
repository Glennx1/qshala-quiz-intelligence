'use client';

import Link from 'next/link';
import { Search, ChevronDown, User } from 'lucide-react';

export default function Topbar() {
  return (
    <header className="sticky top-0 z-20 flex h-16 w-full items-center justify-between border-b border-slate-200/60 bg-slate-50/80 px-6 backdrop-blur-md sm:px-8">
      {/* Left Context / Breadcrumb */}
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-slate-400">Workspace</span>
        <span className="text-[13px] text-slate-300">/</span>
        <span className="text-[13px] font-semibold text-slate-700">QShala Content Vault</span>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-4">
        <Link
          href="/knowledge-base"
          className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200/60 text-slate-600 hover:bg-slate-200 hover:text-slate-900 transition-colors"
          title="Search Questions"
        >
          <Search className="h-3.5 w-3.5" />
        </Link>

        <div className="flex items-center gap-2.5 pl-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-100 text-blue-700 text-[12px] font-bold">
            Q
          </div>
          <button className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700 hover:text-slate-900 transition-colors">
            <span>QShala Team</span>
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
          </button>
        </div>
      </div>
    </header>
  );
}
